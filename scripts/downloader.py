import argparse
import csv
import glob
import json
import os
import re
from math import ceil
from shutil import copyfile, rmtree
from urllib.parse import urlparse

from pyproc import Lpse
from pyproc.helpers import DetilDownloader
from urllib3 import disable_warnings
from urllib3.exceptions import InsecureRequestWarning
from datetime import datetime


def print_info():
    print(r'''    ____        ____                 
   / __ \__  __/ __ \_________  _____
  / /_/ / / / / /_/ / ___/ __ \/ ___/
 / ____/ /_/ / ____/ /  / /_/ / /__  
/_/    \__, /_/   /_/   \____/\___/  
      /____/ v{}                        
SPSE V.4 Downloader
''')


def error_writer(error):
    with open('error.log', 'a', encoding='utf8', errors="ignore") as error_file:
        error_file.write(error+'\n')


def get_folder_name(host, jenis_paket):
    _url = urlparse(host)
    netloc = _url.netloc if _url.netloc != '' else _url.path

    return netloc.lower().replace('.', '_') + '_' + jenis_paket


def get_index_path(host, jenis_paket):
    index_dir = get_folder_name(host, jenis_paket)

    os.makedirs(index_dir, exist_ok=True)

    return os.path.join(index_dir, 'index')


def download_index(host, pool_size, fetch_size, timeout, non_tender):
    lpse_pool = [Lpse(host)]*pool_size
    jenis_paket = 'non_tender' if non_tender else 'tender'
    print("url SPSE       :", lpse_pool[0].host)
    print("versi SPSE     :", lpse_pool[0].version)
    print("last update    :", lpse_pool[0].last_update)
    print("\nIndexing Data")

    for i in lpse_pool:
        i.timeout = timeout

    if non_tender:
        total_data = lpse_pool[0].get_paket_non_tender()['recordsTotal']
    else:
        total_data = lpse_pool[0].get_paket_tender()['recordsTotal']

    batch_size = int(ceil(total_data / fetch_size))
    downloaded_row = 0

    with open(get_index_path(lpse_pool[0].host, jenis_paket), 'w', newline='', encoding='utf8',
              errors="ignore") as index_file:

        writer = csv.writer(index_file, delimiter='|', quoting=csv.QUOTE_ALL)

        for page in range(batch_size):

            lpse = lpse_pool[page % pool_size]

            if non_tender:
                data = lpse.get_paket_non_tender(start=page*fetch_size, length=fetch_size, data_only=True)
            else:
                data = lpse.get_paket_tender(start=page*fetch_size, length=fetch_size, data_only=True)

            writer.writerows(data)

            downloaded_row += len(data)

            yield [page+1, batch_size, downloaded_row]

    del lpse_pool


def get_detil(host, timeout, jenis_paket, total, workers, tahun_anggaran):
    detail_dir = os.path.join(get_folder_name(host, jenis_paket), 'detil')
    index_path = get_index_path(host, jenis_paket)

    os.makedirs(detail_dir, exist_ok=True)

    downloader = DetilDownloader(host, workers=workers, timeout=timeout)
    downloader.spawn_worker()
    downloader.download_dir = detail_dir
    downloader.error_log = detail_dir+".err"
    downloader.is_tender = True if jenis_paket == 'tender' else False
    downloader.total = total
    downloader.workers = workers

    with open(index_path, 'r', encoding='utf8', errors="ignore") as f:
        reader = csv.reader(f, delimiter='|')

        for row in reader:
            tahun_anggaran_data = re.findall(r'(20\d{2})', row[8] if jenis_paket == 'tender' else row[6])

            if not download_by_ta(tahun_anggaran_data, tahun_anggaran):
                continue

            downloader.queue.put(row[0])

    downloader.queue.join()

    del downloader


def parse_tahun_anggaran(tahun_anggaran):
    parsed_ta = tahun_anggaran.strip().split(',')
    error = False

    for i in range(len(parsed_ta)):
        try:
            parsed_ta[i] = int(parsed_ta[i])
        except ValueError:
            parsed_ta[i] = 0

    if len(parsed_ta) > 2:
        error = True

    return error, parsed_ta


def download_by_ta(ta_data, ta_argumen):
    ta_data = [int(i) for i in ta_data]

    for i in ta_data:
        if ta_argumen[0] <= i <= ta_argumen[-1]:
            return True

    return False


def combine_data(host, tender=True, remove=True):
    folder_name = get_folder_name(host, jenis_paket='tender' if tender else 'non_tender')
    detil_dir = os.path.join(folder_name, 'detil', '*')
    detil_combined = os.path.join(folder_name, 'detil.dat')
    detil_all = glob.glob(detil_dir)

    pengumuman_nontender_keys = {
        'id_paket': None,
        'kode_paket': None,
        'nama_paket': None,
        'tanggal_pembuatan': None,
        'keterangan': None,
        'tahap_paket_saat_ini': None,
        'instansi': None,
        'satuan_kerja': None,
        'kategori': None,
        'metode_pengadaan': None,
        'tahun_anggaran': None,
        'nilai_pagu_paket': None,
        'nilai_hps_paket': None,
        'lokasi_pekerjaan': None,
        'npwp': None,
        'nama_pemenang': None,
        'alamat': None,
        'hasil_negosiasi': None,
    }

    pengumuman_keys = {
        'id_paket': None,
        'kode_tender': None,
        'nama_tender': None,
        'tanggal_pembuatan': None,
        'keterangan': None,
        'tahap_tender_saat_ini': None,
        'instansi': None,
        'satuan_kerja': None,
        'kategori': None,
        'sistem_pengadaan': None,
        'tahun_anggaran': None,
        'nilai_pagu_paket': None,
        'nilai_hps_paket': None,
        'lokasi_pekerjaan': None,
        'npwp': None,
        'nama_pemenang': None,
        'alamat': None,
        'harga_penawaran': None,
        'harga_terkoreksi': None,
        'hasil_negosiasi': None,
    }

    with open(detil_combined, 'w', encoding='utf8', errors="ignore") as csvf:
        writer = csv.DictWriter(csvf, fieldnames=pengumuman_keys.keys() if tender else pengumuman_nontender_keys.keys())

        writer.writeheader()

        for detil_file in detil_all:
            detil = pengumuman_keys.copy() if tender else pengumuman_nontender_keys.copy()

            with open(detil_file, 'r', encoding='utf8', errors="ignore") as f:
                data = json.loads(f.read())

            detil['id_paket'] = data['id_paket']

            if data['pengumuman']:
                detil.update((k, data['pengumuman'][k]) for k in detil.keys() & data['pengumuman'].keys())

                detil['lokasi_pekerjaan'] = ' || '.join(detil['lokasi_pekerjaan'])

                if tender:
                    tahap = 'tahap_tender_saat_ini'
                else:
                    tahap = 'tahap_paket_saat_ini'

                if detil[tahap]:
                    detil[tahap] = detil[tahap].strip(r' [...]')

            if data['pemenang']:
                detil.update((k, data['pemenang'][k]) for k in detil.keys() & data['pemenang'].keys())

            writer.writerow(detil)

            del detil

    copy_result(folder_name, remove=remove)


def copy_result(folder_name, remove=True):
    copyfile(os.path.join(folder_name, 'detil.dat'), folder_name + '.csv')

    if os.path.isfile(os.path.join(folder_name, 'detil.err')):
        copyfile(os.path.join(folder_name, 'detil.err'), folder_name + '_error.log')

    if remove:
        rmtree(folder_name)


def main():
    print_info()

    disable_warnings(InsecureRequestWarning)

    parser = argparse.ArgumentParser()
    parser.add_argument("--host", help="Alamat Website LPSE", default=None, type=str)
    parser.add_argument("-r", "--read", help="Membaca host dari file", default=None, type=str)
    parser.add_argument("--tahun-anggaran", help="Tahun Anggaran untuk di download", default=str(datetime.now().year),
                        type=str)
    parser.add_argument("--workers", help="Jumlah worker untuk download detil paket", default=8, type=int)
    parser.add_argument("--pool-size", help="Jumlah koneksi pada pool untuk download index paket", default=4, type=int)
    parser.add_argument("--fetch-size", help="Jumlah row yang didownload per halaman", default=100, type=int)
    parser.add_argument("--timeout", help="Set timeout", default=30, type=int)
    parser.add_argument("--keep", help="Tidak menghapus folder cache", action="store_true")
    parser.add_argument("--non-tender", help="Download paket non tender (penunjukkan langsung)", action="store_true")

    args = parser.parse_args()

    error, tahun_anggaran = parse_tahun_anggaran(args.tahun_anggaran)

    if error:
        print("ERROR: format tahun anggaran tidak dikenal ", args.tahun_anggaran)
        exit(1)

    if args.host:
        host_list = args.host.strip().split(',')
    elif args.read:
        with open(args.read, 'r', encoding='utf8', errors="ignore") as host_file:
            host_list = host_file.read().strip().split()
    else:
        parser.print_help()
        print("\nERROR: Argumen --host atau --read tidak ditemukan!")
        exit(1)

    # download index

    for host in host_list:
        print("="*len(host))
        print(host)
        print("="*len(host))
        print("tahun anggaran :", tahun_anggaran)

        try:
            total = 0
            for downloadinfo in download_index(host, args.pool_size, args.fetch_size, args.timeout, args.non_tender):
                print("- halaman {} of {} ({} row)".format(*downloadinfo), end='\r')
                total = downloadinfo[-1]
            print("\n- download selesai\n")

            print("Downloading")
            get_detil(host=host, jenis_paket='non_tender' if args.non_tender else 'tender', total=total,
                      workers=args.workers, tahun_anggaran=tahun_anggaran, timeout=args.timeout)
            print("\n- download selesai\n")

            print("Menggabungkan Data")
            combine_data(host, False if args.non_tender else True, False if args.keep else True)
            print("- proses selesai")
        except KeyboardInterrupt:
            print("\nERROR: Proses dibatalkan oleh user, bye!")
        except Exception as e:
            print("ERROR:", e)
            error_writer("{}|{}".format(host, str(e)))


def download():
    try:
        main()
    except KeyboardInterrupt:
        print("\nERROR: Proses dibatalkan oleh user, bye!")


if __name__ == '__main__':
    download()
