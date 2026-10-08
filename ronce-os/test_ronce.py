"""Test otomatis Ronce.

Jalankan:  python test_ronce.py
Atau:      python -m unittest test_ronce -v

Semua test di sini offline: tidak memanggil API Sectors atau AI.
Data uji sintetis, bukan data pasar nyata.
"""
from __future__ import annotations

import json
import re
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from config import Config
from core import compose, render, rewrite

WIB = ZoneInfo("Asia/Jakarta")


# ------------------------------------------------------------------ data uji

def berita(judul, isi="", simbol=None, sumber="https://investasi.kontan.co.id/news/x"):
    return {
        "title": judul,
        "body": isi or judul,
        "source": sumber,
        "timestamp": "2026-10-05T10:00:00",
        "symbols": simbol or ["BBCA.JK"],
    }


def data_uji(*, berita_list=None, filings=None, aksi=None):
    return {
        "tanggal": "2026-10-05",
        "jendela": ["2026-10-04", "2026-10-05"],
        "_sumber": "uji",
        "berita": {"results": berita_list if berita_list is not None
                   else [berita("BBCA umumkan dividen tunai 100 rupiah")]},
        "filings": {"results": filings if filings is not None else []},
        "corp_actions": aksi if aksi is not None else {},
    }


def filing(pemilik="MUFG Bank", simbol="ADMF.JK", sebelum=18.89, sesudah=14.36,
           jumlah=55938400, harga=7800, jenis="sell"):
    return {
        "symbol": simbol, "holder_name": pemilik,
        "share_percentage_before": sebelum, "share_percentage_after": sesudah,
        "amount_transaction": jumlah, "price": harga, "transaction_type": jenis,
    }


def dividen(simbol="DADA.JK", jumlah=0.27, ex="2026-10-05", bayar="2026-10-28"):
    return {"symbol": simbol, "dividend_amount": jumlah,
            "ex_date": ex, "payment_date": bayar}


def agm(simbol="KOTA.JK", tanggal="2026-10-06", waktu="10:00:00",
        tempat="Azana Suite Hotel"):
    return {"symbol": simbol, "agm_date": tanggal, "agm_time": waktu,
            "agm_place": tempat, "recording_date": "2026-09-30"}


# ------------------------------------------------------------------ test

class TestKonfigurasi(unittest.TestCase):
    """config.py membaca .env dengan benar."""

    def test_ringkas_tidak_bocorkan_rahasia(self):
        c = Config(sectors_key="RAHASIA123", ai_key="RAHASIA456",
                   ai_base="https://api.test/v1", ai_model="model-x")
        ringkas = c.ringkas()
        teks = json.dumps(ringkas)
        self.assertNotIn("RAHASIA123", teks)
        self.assertNotIn("RAHASIA456", teks)
        self.assertIn("ADA", teks)

    def test_punya_sectors(self):
        self.assertTrue(Config(sectors_key="x").punya_sectors())
        self.assertFalse(Config(sectors_key="").punya_sectors())

    def test_punya_ai_butuh_ketiganya(self):
        self.assertTrue(Config(ai_base="u", ai_key="k", ai_model="m").punya_ai())
        self.assertFalse(Config(ai_base="u", ai_key="k", ai_model="").punya_ai())
        self.assertFalse(Config(ai_base="", ai_key="k", ai_model="m").punya_ai())

    def test_mode_offline(self):
        self.assertEqual(Config(offline=True).ringkas()["mode"], "offline")
        self.assertEqual(Config(offline=False).ringkas()["mode"], "online")


class TestNamaMedia(unittest.TestCase):
    """.nama_media() menerjemahkan domain jadi nama yang enak dibaca."""

    def test_kontan_subdomain(self):
        self.assertEqual(
            compose.nama_media("https://investasi.kontan.co.id/news/x"), "Kontan")

    def test_cnbc(self):
        self.assertEqual(
            compose.nama_media("https://www.cnbcindonesia.com/market/1"), "CNBC Indonesia")

    def test_media_tidak_dikenal(self):
        hasil = compose.nama_media("https://mediabaru.example.com/a")
        self.assertTrue(hasil)
        self.assertNotIn("http", hasil)

    def test_kosong(self):
        self.assertEqual(compose.nama_media(""), "")


class TestFormat(unittest.TestCase):
    """Format angka dan tanggal."""

    def test_persen(self):
        self.assertEqual(compose.fmt_persen(14.36), "14.36%")
        self.assertEqual(compose.fmt_persen(None), "-")

    def test_angka_pakai_titik_ribuan(self):
        self.assertEqual(compose.fmt_angka(55938400), "55.938.400")

    def test_tanggal_bahasa_indonesia(self):
        self.assertEqual(compose.fmt_tanggal("2026-10-28"), "28 Oktober 2026")
        self.assertEqual(compose.fmt_tanggal("2026-01-01"), "1 Januari 2026")


class TestBersihkanKode(unittest.TestCase):
    def test_buang_suffix_jk(self):
        self.assertEqual(compose.bersihkan_kode("ADMF.JK"), "ADMF")

    def test_tanpa_suffix(self):
        self.assertEqual(compose.bersihkan_kode("BBCA"), "BBCA")

    def test_kosong(self):
        self.assertEqual(compose.bersihkan_kode(""), "")
        self.assertEqual(compose.bersihkan_kode(None), "")


class TestPendekkanNama(unittest.TestCase):
    """Nama perusahaan panjang diganti kode emiten."""

    def test_ganti_nama_panjang(self):
        hasil = compose.pendekkan_nama(
            "PT Wulandari Bangun Laksana Tbk membagikan dividen", "BSBK")
        self.assertIn("BSBK", hasil)
        self.assertNotIn("Wulandari", hasil)

    def test_nama_tanpa_pt(self):
        hasil = compose.pendekkan_nama(
            "Golden Energy Mines Tbk membagikan dividen", "GEMS")
        self.assertIn("GEMS", hasil)

    def test_tanpa_emiten_tidak_diubah(self):
        teks = "PT Contoh Panjang Tbk melakukan sesuatu"
        self.assertEqual(compose.pendekkan_nama(teks, ""), teks)


class TestRapikanJudul(unittest.TestCase):
    """Judul harus pendek, bahasa Indonesia, dan punya subjek."""

    def test_pakai_kalimat_pertama_narasi(self):
        hasil = compose.rapikan_judul(
            "", "GEMS",
            "GEMS membagikan dividen interim Rp 622 per saham. Yield 7 persen.")
        self.assertTrue(hasil.startswith("GEMS"))

    def test_judul_inggris_ditolak(self):
        hasil = compose.rapikan_judul(
            "OJK Asks Banks to Weigh IT Investment Needs", "BMRI", "")
        self.assertEqual(hasil, "")

    def test_judul_maksimal_60_karakter(self):
        panjang = ("PT Perusahaan Sangat Panjang Sekali Namanya Tbk "
                   "melakukan akuisisi besar terhadap perusahaan lain di Jakarta")
        hasil = compose.rapikan_judul("", "TEST", panjang)
        self.assertLessEqual(len(hasil), 60)

    def test_tidak_berakhir_kata_penggantung(self):
        panjang = ("TEST akan melakukan akuisisi besar terhadap perusahaan "
                   "lain di Jakarta kepada pihak yang tidak disebutkan namanya")
        hasil = compose.rapikan_judul("", "TEST", panjang)
        self.assertFalse(re.search(r"\s(kepada|untuk|dengan|yang|di)$", hasil))


class TestPilihHeadline(unittest.TestCase):
    """Pemilihan dan dedup berita."""

    def test_urut_penting_dulu(self):
        data = data_uji(berita_list=[
            berita("Perusahaan kecil naik sedikit", simbol=["XXXX.JK"]),
            berita("BEI ubah aturan batas harga saham", simbol=["BBCA.JK"]),
        ])
        hasil = compose.pilih_headline(data, maks=2)
        self.assertIn("BEI", hasil[0]["judul"])

    def test_buang_berita_kembar(self):
        data = data_uji(berita_list=[
            berita("PT Bukit Uluwatu Villa Tbk Plans Rights Issue Rp 1.53 Trillion",
                   simbol=["BUVA.JK"]),
            berita("PT Bukit Uluwatu Villa Tbk Plans Rights Issue Rp 1.54 Trillion",
                   simbol=["BUVA.JK"]),
        ])
        hasil = compose.pilih_headline(data, maks=5)
        self.assertEqual(len(hasil), 1)

    def test_hormati_batas_maks(self):
        data = data_uji(berita_list=[
            berita(f"Perusahaan {i} melakukan aksi korporasi berbeda", simbol=[f"AA{i}A.JK"])
            for i in range(10)])
        self.assertEqual(len(compose.pilih_headline(data, maks=3)), 3)

    def test_data_kosong_tidak_error(self):
        self.assertEqual(compose.pilih_headline({}, maks=3), [])


class TestBagianKeterbukaan(unittest.TestCase):
    def test_baca_transaksi(self):
        data = data_uji(filings=[filing()])
        entri, media = compose.bagian_keterbukaan(data)
        self.assertEqual(len(entri), 1)
        self.assertIn("MUFG", entri[0]["narasi"])
        self.assertIn("14.36", entri[0]["narasi"])
        self.assertEqual(entri[0]["emiten"], "ADMF")
        self.assertIn("Sectors", media)

    def test_lewati_persen_tidak_berubah(self):
        # 3.17% -> 3.17% bukan transaksi nyata, harus dilewati.
        data = data_uji(filings=[filing(sebelum=3.17, sesudah=3.17)])
        entri, _ = compose.bagian_keterbukaan(data)
        self.assertEqual(entri, [])

    def test_hormati_batas_maks(self):
        data = data_uji(filings=[filing(simbol=f"AAA{i}.JK") for i in range(10)])
        entri, _ = compose.bagian_keterbukaan(data, maks=3)
        self.assertEqual(len(entri), 3)


class TestBagianAksiKorporasi(unittest.TestCase):
    def test_dividen(self):
        data = data_uji(aksi={"dividend": [dividen()]})
        entri, _ = compose.bagian_aksi_korporasi(data)
        self.assertEqual(len(entri), 1)
        self.assertIn("DADA", entri[0]["narasi"])
        self.assertIn("28 Oktober 2026", entri[0]["narasi"])

    def test_rights_issue(self):
        data = data_uji(aksi={"right_issue": [{
            "symbol": "ENRG.JK", "price": 310,
            "trading_period_start": "2026-10-08",
            "trading_period_end": "2026-10-21"}]})
        entri, _ = compose.bagian_aksi_korporasi(data)
        self.assertIn("ENRG", entri[0]["narasi"])
        self.assertIn("rights issue", entri[0]["narasi"].lower())

    def test_kosong(self):
        entri, _ = compose.bagian_aksi_korporasi(data_uji(aksi={}))
        self.assertEqual(entri, [])


class TestBagianRups(unittest.TestCase):
    def test_rups(self):
        data = data_uji(aksi={"agm": [agm()]})
        entri, _ = compose.bagian_rups(data)
        self.assertEqual(len(entri), 1)
        self.assertIn("KOTA", entri[0]["narasi"])
        self.assertIn("6 Oktober 2026", entri[0]["narasi"])

    def test_tempat_panjang_dipotong(self):
        tempat = "Tempat yang sangat panjang sekali " * 5
        data = data_uji(aksi={"agm": [agm(tempat=tempat)]})
        entri, _ = compose.bagian_rups(data)
        self.assertLessEqual(len(entri[0]["narasi"]), 200)


class TestBagianSorotan(unittest.TestCase):
    def test_harga_tampil(self):
        harga = {"BBCA.JK": {"close": 6100, "tanggal": "2026-10-02",
                             "ubah_persen": 1.67}}
        entri, _, judul = compose.bagian_sorotan(harga)
        self.assertEqual(len(entri), 1)
        self.assertEqual(entri[0]["emiten"], "BBCA")
        self.assertIn("6100", entri[0]["narasi"])
        self.assertIn("+1.67%", entri[0]["narasi"])
        self.assertIn("2 Oktober 2026", judul)

    def test_tanpa_perubahan(self):
        harga = {"BBCA.JK": {"close": 6100, "tanggal": "2026-10-02",
                             "ubah_persen": None}}
        entri, _, _ = compose.bagian_sorotan(harga)
        self.assertIn("6100", entri[0]["narasi"])
        self.assertNotIn("%", entri[0]["narasi"])


class TestBagiPost(unittest.TestCase):
    """Pembagian jadi beberapa post."""

    def test_satu_post_kalau_muat(self):
        posts = compose.bagi_post("JUDUL", "ringkasan", [("BAGIAN", [
            {"emiten": "AAAA", "narasi": "Isi pendek."}])], ["Kontan"])
        self.assertEqual(len(posts), 1)

    def test_batas_byte_dipatuhi(self):
        bagian = [("BAGIAN", [
            {"emiten": f"AAA{i}", "narasi": "Isi yang cukup panjang " * 8}
            for i in range(10)])]
        posts = compose.bagi_post("JUDUL PANJANG " * 3, "ringkasan panjang " * 3,
                                  bagian, ["Kontan"], batas_byte=500)
        for p in posts:
            self.assertLessEqual(len(p.encode("utf-8")), 500)

    def test_entri_tidak_terpotong(self):
        isi = "Kalimat lengkap yang tidak boleh dipotong di tengah."
        bagian = [("BAGIAN", [{"emiten": "AAAA", "narasi": isi}])]
        posts = compose.bagi_post("J", "r", bagian, [])
        self.assertIn(isi, posts[0])

    def test_sumber_di_akhir_sekali(self):
        bagian = [("BAGIAN", [{"emiten": "AAAA", "narasi": "Isi."}])]
        posts = compose.bagi_post("J", "r", bagian, ["Kontan", "CNBC Indonesia"])
        gabung = "\n".join(posts)
        self.assertEqual(gabung.count("Sumber:"), 1)
        self.assertIn("Kontan, CNBC Indonesia", gabung)

    def test_tanpa_sumber(self):
        bagian = [("BAGIAN", [{"emiten": "AAAA", "narasi": "Isi."}])]
        posts = compose.bagi_post("J", "r", bagian, [])
        self.assertNotIn("Sumber:", "\n".join(posts))


class TestSusun(unittest.TestCase):
    """susun() menggabungkan semuanya."""

    def setUp(self):
        self.tanggal = datetime(2026, 10, 5, 12, 0, tzinfo=WIB)

    def test_hasil_lengkap(self):
        data = data_uji(
            berita_list=[berita("BEI ubah aturan batas harga", simbol=["BBCA.JK"])],
            filings=[filing()],
            aksi={"dividend": [dividen()]})
        ditulis = [{"judul": "BEI ubah aturan batas harga",
                    "emiten": "BBCA", "sumber": "https://investasi.kontan.co.id/x",
                    "narasi": "BEI mengubah aturan batas harga saham."}]
        warta = compose.susun(data, ditulis, {}, self.tanggal)

        self.assertIn("WARTA RONCE 05 Oktober 2026", warta["judul"])
        self.assertTrue(warta["ringkasan"])
        self.assertIn("HEADLINE UTAMA", warta["bagian"])
        self.assertIn("KETERBUKAAN INFORMASI", warta["bagian"])
        self.assertGreater(warta["jumlah_post"], 0)

    def test_status_publikasi_selalu_aman(self):
        warta = compose.susun(data_uji(), [], {}, self.tanggal)
        self.assertFalse(warta["publishable"])
        self.assertEqual(warta["editor_approval"], "required")
        self.assertFalse(warta["api_write"])

    def test_bagian_kosong_tidak_muncul(self):
        warta = compose.susun(data_uji(filings=[], aksi={}), [], {}, self.tanggal)
        self.assertNotIn("KETERBUKAAN INFORMASI", warta["bagian"])
        self.assertNotIn("RUPS", warta["bagian"])

    def test_semua_post_dalam_batas(self):
        banyak = [berita(f"Berita {i} tentang dividen dan akuisisi besar",
                         simbol=["AAAA.JK"]) for i in range(6)]
        ditulis = [{"judul": f"Judul {i}", "emiten": "AAAA",
                    "sumber": "https://investasi.kontan.co.id/x",
                    "narasi": "Narasi panjang tentang kejadian penting " * 3}
                   for i in range(6)]
        warta = compose.susun(data_uji(berita_list=banyak), ditulis, {}, self.tanggal)
        for p in warta["posts"]:
            self.assertLessEqual(len(p.encode("utf-8")), 500)


class TestRewriteSederhana(unittest.TestCase):
    """Penulisan cadangan tanpa AI."""

    def test_potong_tiga_kalimat(self):
        isi = "Satu. Dua. Tiga. Empat. Lima."
        hasil = rewrite.tulis_ulang_sederhana("Judul", isi, "AAAA")
        self.assertEqual(hasil, "Satu. Dua. Tiga.")

    def test_isi_kosong_pakai_judul(self):
        hasil = rewrite.tulis_ulang_sederhana("Judul saja", "", "AAAA")
        self.assertEqual(hasil, "Judul saja")

    def test_tidak_mengarang(self):
        # Kalau isi kosong dan judul kosong, hasilnya kosong.
        hasil = rewrite.tulis_ulang_sederhana("", "", "AAAA")
        self.assertEqual(hasil, "")


class TestRewriteBanyak(unittest.TestCase):
    """Penulisan banyak sekaligus, tanpa AI (offline)."""

    def test_tanpa_ai_pakai_sederhana(self):
        hasil = rewrite.tulis_ulang_banyak(
            [{"judul": "Judul", "isi": "Isi berita. Baris kedua.", "emiten": "AAAA"}],
            verbose=False)
        self.assertEqual(len(hasil), 1)
        self.assertEqual(hasil[0]["cara"], "sederhana")
        self.assertIn("narasi", hasil[0])

    def test_ai_gagal_pakai_cadangan(self):
        # base_url salah -> harus jatuh ke penulisan sederhana, bukan error.
        hasil = rewrite.tulis_ulang_banyak(
            [{"judul": "Judul", "isi": "Isi berita asli.", "emiten": "AAAA"}],
            base_url="http://127.0.0.1:1/tidak-ada", key="x", model="y",
            timeout=2, verbose=False)
        self.assertEqual(hasil[0]["cara"], "sederhana")


class TestRender(unittest.TestCase):
    """Keluaran file."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.out = Path(self.tmp.name)
        self.warta = compose.susun(data_uji(
            berita_list=[berita("BEI ubah aturan")],
            filings=[filing()]),
            [{"judul": "BEI ubah aturan", "emiten": "BBCA",
              "sumber": "https://investasi.kontan.co.id/x",
              "narasi": "BEI mengubah aturan."}],
            {}, datetime(2026, 10, 5, 12, 0, tzinfo=WIB))

    def test_tiga_file_dibuat(self):
        hasil = render.simpan_semua(self.warta, self.out)
        # Tiga berkas wajib; 'web' tambahan muncul bila folder web ada.
        self.assertTrue({"json", "teks", "markdown"}.issubset(set(hasil)))
        for jenis in ("json", "teks", "markdown"):
            path = hasil[jenis]
            self.assertTrue(path.exists())
            self.assertGreater(path.stat().st_size, 0)

    def test_json_bisa_dibaca_ulang(self):
        hasil = render.simpan_semua(self.warta, self.out)
        isi = json.loads(hasil["json"].read_text(encoding="utf-8"))
        self.assertEqual(isi["judul"], self.warta["judul"])
        self.assertEqual(isi["jumlah_post"], self.warta["jumlah_post"])

    def test_teks_memuat_semua_post(self):
        hasil = render.simpan_semua(self.warta, self.out)
        teks = hasil["teks"].read_text(encoding="utf-8")
        for p in self.warta["posts"]:
            self.assertIn(p.split("\n")[0][:30], teks)

    def test_markdown_ada_tabel_cek(self):
        hasil = render.simpan_semua(self.warta, self.out)
        md = hasil["markdown"].read_text(encoding="utf-8")
        self.assertIn("CEK TEKNIS", md)
        self.assertIn("belum boleh dipublikasikan", md.lower())

    def test_simpan_web_tidak_menimpa_data_web_asli(self):
        """Folder sementara tidak boleh menulis ke web/ yang sebenarnya.

        Ini pernah terjadi: menjalankan test menimpa web/warta.json dengan
        data uji, sehingga website menampilkan edisi yang salah.
        """
        asli = Path(__file__).resolve().parent / "web" / "warta.json"
        sebelum = asli.read_text(encoding="utf-8") if asli.exists() else None

        hasil = render.simpan_semua(self.warta, self.out)

        # Folder sementara tidak boleh menghasilkan tulisan ke web/.
        self.assertNotIn("web", hasil)
        if sebelum is not None:
            self.assertEqual(asli.read_text(encoding="utf-8"), sebelum,
                             "test menimpa data web yang sebenarnya")

    def test_simpan_web_menulis_bila_dipaksa(self):
        """Dengan paksa=True, salinan web tetap dibuat (dipakai ronce.py web)."""
        asli = Path(__file__).resolve().parent / "web" / "warta.json"
        sebelum = asli.read_text(encoding="utf-8") if asli.exists() else None

        target = render.simpan_web(self.warta, self.out, paksa=True)
        if target is None:
            self.skipTest("folder web/ tidak ada")

        sesudah = json.loads(target.read_text(encoding="utf-8"))
        self.assertEqual(sesudah["judul"], self.warta["judul"])

        # Kembalikan isi semula supaya tidak mengganggu edisi sebenarnya.
        if sebelum is not None:
            asli.write_text(sebelum, encoding="utf-8")


class TestTidakAdaRahasiaDiOutput(unittest.TestCase):
    """Hasil tidak boleh memuat nilai rahasia."""

    def test_tidak_ada_key_di_hasil(self):
        warta = compose.susun(data_uji(), [], {}, datetime(2026, 10, 5, tzinfo=WIB))
        teks = json.dumps(warta, ensure_ascii=False)
        for pola in (r"sk-[a-zA-Z0-9]{16,}", r"Bearer\s+\S{20,}",
                     r"SECTORS_API_KEY"):
            self.assertIsNone(re.search(pola, teks),
                              f"pola rahasia ditemukan: {pola}")


class TestBatasanSistem(unittest.TestCase):
    """Sistem tidak boleh memposting sendiri."""

    def test_selalu_publishable_false(self):
        for _ in range(3):
            warta = compose.susun(data_uji(), [], {}, datetime(2026, 10, 5, tzinfo=WIB))
            self.assertFalse(warta["publishable"])

    def test_api_write_selalu_false(self):
        warta = compose.susun(data_uji(), [], {}, datetime(2026, 10, 5, tzinfo=WIB))
        self.assertFalse(warta["api_write"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
