/* Ronce — logika antarmuka
   Tanpa pustaka luar. Semua data dibaca dari Warta yang dihasilkan ronce.py.
   Tata letak: sidebar + Orbit (pintu masuk satu textbox).
   Prinsip: umpan balik instan, gerak bisa dihentikan, hormati reduced-motion. */

const KURANGI_GERAK = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

const state = {
  warta: null,
  indeks: [],
  halaman: 'orbit',
};

/* ---------------------------------------------------------------- bantu */

const $ = (s, akar = document) => akar.querySelector(s);
const $$ = (s, akar = document) => [...akar.querySelectorAll(s)];

const esc = (t) => String(t ?? '')
  .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
  .replace(/"/g, '&quot;');

const rupiah = (n) => {
  const x = Number(n);
  if (!isFinite(x)) return '—';
  return 'Rp' + x.toLocaleString('id-ID');
};

const persen = (n) => {
  const x = Number(n);
  if (!isFinite(x)) return '—';
  return (x >= 0 ? '+' : '') + x.toFixed(2) + '%';
};

/* Sapaan menyesuaikan jam, tidak mengganggu. */
function sapaan() {
  const j = new Date().getHours();
  if (j < 11) return 'Selamat pagi.';
  if (j < 15) return 'Selamat siang.';
  if (j < 19) return 'Selamat sore.';
  return 'Selamat malam.';
}

/* ---------------------------------------------------------------- halaman */

/* Daftar halaman — sesuai konsep awal: Orbit, Warta, Jelajah, Kalender,
   Emiten, Arsip, lalu Disimpan.
   'cari' bukan halaman menu: ia halaman hasil yang dibuka dari textbox Orbit,
   persis seperti konsep awal ("Enter membuka halaman hasil lengkap"). */
const HALAMAN_SAH = ['orbit', 'warta', 'jelajah', 'kalender', 'emiten', 'disimpan', 'profil', 'cari'];

function pindahHalaman(nama, { simpan = true } = {}) {
  if (!HALAMAN_SAH.includes(nama)) nama = 'orbit';
  state.halaman = nama;

  $$('.halaman').forEach((el) => { el.hidden = true; });
  const target = $('#hal-' + nama);
  if (target) target.hidden = false;

  // Footer hanya tampil di halaman Profil proyek.
  const footer = $('#footer');
  if (footer) footer.hidden = nama !== 'profil';

  // Tandai item aktif di sidebar dan navigasi bawah.
  $$('.nav-item, .nb-item').forEach((a) => {
    if (a.dataset.halaman === nama) a.setAttribute('aria-current', 'page');
    else a.removeAttribute('aria-current');
  });

  window.scrollTo({ top: 0, behavior: KURANGI_GERAK ? 'auto' : 'smooth' });
  if (simpan) {
    history.replaceState(null, '', '#' + nama);
    try { localStorage.setItem('ronce-terakhir', nama); } catch (e) { /* diabaikan */ }
  }
  if (nama === 'cari') setTimeout(() => $('#input-cari')?.focus(), 100);
  if (nama === 'orbit') setTimeout(() => $('#orbit-input')?.focus(), 100);
}

/* ---------------------------------------------------------------- sidebar
   Bisa dibuka-tutup. Keadaan disimpan supaya tidak berubah-ubah
   tiap kali halaman dimuat ulang. */

const KUNCI_SIDEBAR = 'ronce-sidebar-tutup';

function pasangSidebar() {
  const app = $('#app');
  const tombol = $('#sidebar-tombol');
  if (!app || !tombol) return;

  const ikon = tombol.querySelector('use');

  const terapkan = (tutup, { simpan = true } = {}) => {
    app.classList.toggle('tutup', tutup);
    tombol.setAttribute('aria-expanded', String(!tutup));
    tombol.setAttribute('aria-label', tutup ? 'Buka menu' : 'Tutup menu');
    if (ikon) ikon.setAttribute('href', tutup ? '#i-buka-kiri' : '#i-tutup-kiri');
    if (simpan) {
      try { localStorage.setItem(KUNCI_SIDEBAR, tutup ? '1' : '0'); } catch (e) { /* diabaikan */ }
    }
  };

  let tutup = false;
  try { tutup = localStorage.getItem(KUNCI_SIDEBAR) === '1'; } catch (e) { /* diabaikan */ }

  // Di layar kecil sidebar memang sudah jadi kepala ringkas, jadi
  // keadaan tertutup tidak berlaku di sana.
  const sempit = window.matchMedia('(max-width: 900px)').matches;
  terapkan(sempit ? false : tutup, { simpan: false });

  tombol.addEventListener('click', () => terapkan(!app.classList.contains('tutup')));

  // Pintasan: [ membuka/menutup sidebar, seperti editor kode.
  document.addEventListener('keydown', (ev) => {
    if (ev.key === '[' && !ev.ctrlKey && !ev.metaKey) {
      const t = ev.target;
      const sedangMenulis = t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA'
        || t.isContentEditable);
      if (sedangMenulis) return;
      ev.preventDefault();
      terapkan(!app.classList.contains('tutup'));
    }
  });
}

/* ---------------------------------------------------------------- panel */

let fokusSebelumPanel = null;

function bukaPanel(judul, isiHtml, opsiSimpan = null) {
  fokusSebelumPanel = document.activeElement;
  $('#panel-judul').textContent = judul;
  $('#panel-isi').innerHTML = isiHtml
    + (opsiSimpan ? `
      <div class="simpan-baris">
        <button type="button" class="tombol ${sudahDisimpan(opsiSimpan.teks) ? 'simpan-aktif' : ''}"
                id="panel-simpan">
          ${sudahDisimpan(opsiSimpan.teks) ? 'Tersimpan' : 'Simpan'}
        </button>
      </div>` : '');
  $('#panel').classList.add('buka');
  $('#panel').setAttribute('aria-hidden', 'false');
  $('#overlay').classList.add('buka');
  document.body.style.overflow = 'hidden';
  $('#panel-tutup').focus();

  const tombolSimpan = $('#panel-simpan');
  if (tombolSimpan && opsiSimpan) {
    tombolSimpan.addEventListener('click', () => {
      const sekarang = togolSimpan(opsiSimpan);
      tombolSimpan.textContent = sekarang ? 'Tersimpan' : 'Simpan';
      tombolSimpan.classList.toggle('simpan-aktif', sekarang);
      renderDisimpan(state.warta);
    });
  }
}

function tutupPanel() {
  $('#panel').classList.remove('buka');
  $('#panel').setAttribute('aria-hidden', 'true');
  $('#overlay').classList.remove('buka');
  document.body.style.overflow = '';
  // Fokus kembali ke elemen asal — jangan biarkan pengguna kehilangan tempat.
  if (fokusSebelumPanel && document.contains(fokusSebelumPanel)) {
    fokusSebelumPanel.focus();
  }
  fokusSebelumPanel = null;
}

/* ---------------------------------------------------------------- angka statistik
   Angka statistik ditulis apa adanya, tanpa animasi hitung.

   Alasan: animasi hitung sempat menampilkan angka yang belum final
   (mis. 2/3/4/2 padahal nilai sebenarnya 3/5/7/3) pada tangkapan layar,
   cetak, atau pembaca yang tidak menjalankan animasi. Untuk produk data,
   angka yang salah walau sesaat tidak bisa diterima. Kehalusan tampilan
   tetap dijaga lewat animasi masuk (fade) di CSS. */

function tulisStatistik(kotak) {
  $$('[data-angka]', kotak).forEach((el) => {
    const n = Number(el.dataset.angka) || 0;
    el.textContent = n.toLocaleString('id-ID');
  });
}

/* ---------------------------------------------------------------- grafik */

function gambarGrafik(g) {
  const kotak = $('#grafik');
  if (!kotak) return;
  const titik = (g && g.titik) || [];
  if (titik.length < 2) {
    kotak.innerHTML = '<p class="samar kecil" style="padding:24px 0">Data harga belum cukup untuk menggambar grafik.</p>';
    return;
  }

  const L = 640, T = 240, P = { atas: 34, kanan: 16, bawah: 42, kiri: 16 };
  const lw = L - P.kiri - P.kanan;
  const lt = T - P.atas - P.bawah;

  // Skala linier — proporsi batang harus jujur. Pada bagan batang, panjang
  // batang ITU datanya; skala logaritma akan membuat batang kecil tampak
  // jauh lebih besar daripada nilainya. Karena itu skala linier dipakai,
  // dan batang terkecil diberi tinggi minimum supaya tetap terlihat
  // sebagai batang. Angka pasti selalu tertulis di atas tiap batang.
  const maks = Math.max(...titik.map((d) => Number(d.nilai) || 0)) || 1;
  const TINGGI_MIN = 4;

  const lebar = Math.min(72, lw / titik.length * 0.55);
  const langkah = lw / titik.length;

  const batang = titik.map((d, i) => {
    const nilai = Number(d.nilai) || 0;
    const tinggi = Math.max(TINGGI_MIN, (nilai / maks) * lt);
    const x = P.kiri + langkah * i + (langkah - lebar) / 2;
    const y = P.atas + lt - tinggi;
    return `
      <g class="batang" style="animation-delay:${i * 100}ms">
        <rect x="${x.toFixed(1)}" y="${y.toFixed(1)}" width="${lebar.toFixed(1)}"
              height="${tinggi.toFixed(1)}"
              rx="4" fill="#234ae8" opacity="0.9">
          <title>${esc(d.label)}: ${rupiah(d.nilai)}</title>
        </rect>
        <text class="sumbu-teks" x="${(x + lebar / 2).toFixed(1)}" y="${(y - 10).toFixed(1)}"
              text-anchor="middle" style="fill:#f2f4f1;font-size:12px">${rupiah(d.nilai)}</text>
        <text class="sumbu-teks" x="${(x + lebar / 2).toFixed(1)}" y="${T - 16}"
              text-anchor="middle" style="fill:#b8c4c5">${esc(d.label)}</text>
      </g>`;
  }).join('');

  kotak.innerHTML = `
    <svg viewBox="0 0 ${L} ${T}" role="img"
         aria-label="Perbandingan harga penutupan ${titik.length} emiten">
      <line class="sumbu" x1="${P.kiri}" y1="${P.atas + lt}" x2="${L - P.kanan}" y2="${P.atas + lt}"/>
      ${batang}
    </svg>
    ${g.catatan ? `<p class="samar kecil" style="margin-top:14px">${esc(g.catatan)}</p>` : ''}`;
}

/* ---------------------------------------------------------------- React Bits
   Adaptasi dari reactbits.dev:
   - Spotlight Card : sorot mengikuti kursor di dalam kartu
   - Fade Content   : elemen muncul saat masuk layar
   - Animated Content: anak muncul berurutan
   Semua hormati prefers-reduced-motion. */

function pasangSpotlight(akar = document) {
  if (KURANGI_GERAK) return;
  $$('.kartu', akar).forEach((kartu) => {
    if (kartu.dataset.sorotPasang) return;
    kartu.dataset.sorotPasang = '1';
    kartu.classList.add('sorot');
    kartu.addEventListener('pointermove', (ev) => {
      const r = kartu.getBoundingClientRect();
      kartu.style.setProperty('--x', `${ev.clientX - r.left}px`);
      kartu.style.setProperty('--y', `${ev.clientY - r.top}px`);
    });
  });
}

const pengamat = ('IntersectionObserver' in window) && !KURANGI_GERAK
  ? new IntersectionObserver((masuk) => {
      masuk.forEach((m) => {
        if (m.isIntersecting) {
          m.target.classList.add('tampak');
          pengamat.unobserve(m.target);
        }
      });
    }, { threshold: 0.12, rootMargin: '0px 0px -60px 0px' })
  : null;

function pasangFade(akar = document) {
  const sasaran = $$('.fade-masuk, .berurutan', akar);
  if (!pengamat) {
    sasaran.forEach((el) => el.classList.add('tampak'));
    return;
  }
  sasaran.forEach((el) => pengamat.observe(el));
}

/* ---------------------------------------------------------------- Orbit
   Pintu masuk: sapaan + satu textbox + chip. Sengaja bersih.
   Orbit TIDAK membalas dengan esai AI. Ia menunjukkan hasil yang bisa
   diperiksa: emiten, berita, bagian, dan halaman. */

/* Indeks pencarian dibangun sekali dari Warta. */
function bangunIndeks(w) {
  const idx = [];

  idx.push({
    jenis: 'Halaman', kode: 'WARTA',
    judul: w.judul || 'Warta hari ini',
    teks: [w.judul, w.ringkasan, w.tanggal, 'warta hari ini edisi']
      .filter(Boolean).join(' ').toLowerCase(),
    aksi: () => pindahHalaman('warta'),
  });

  for (const [nama, isi] of Object.entries(w.bagian || {})) {
    const namaBersih = nama.split(' (')[0];
    for (const e of isi) {
      idx.push({
        jenis: 'Berita',
        kode: e.emiten || '',
        judul: e.judul || (e.narasi || '').split('.')[0] || '',
        teks: [e.emiten, e.judul, e.narasi, e.media, namaBersih]
          .filter(Boolean).join(' ').toLowerCase(),
        emiten: e.emiten || '',
        bagian: namaBersih,
        narasi: e.narasi || '',
        media: e.media || '',
        aksi: () => {
          bukaPanel(e.emiten || namaBersih, `
            ${e.judul ? `<h3 style="margin-bottom:12px">${esc(e.judul)}</h3>` : ''}
            <p>${esc(e.narasi || '')}</p>
            ${e.media ? `<p class="samar kecil">Sumber: ${esc(e.media)}</p>` : ''}
            ${e.emiten ? `<p class="samar kecil">Emiten: <span class="mono">${esc(e.emiten)}</span></p>` : ''}
            <p class="samar kecil">Bagian: ${esc(namaBersih)}</p>`);
        },
      });
    }
  }

  // Satu entri per emiten unik, agar saran tidak berulang.
  const sudah = new Set();
  for (const e of idx) {
    if (!e.emiten || sudah.has(e.emiten)) continue;
    sudah.add(e.emiten);
    idx.push({
      jenis: 'Emiten', kode: e.emiten,
      judul: `${e.emiten} — ${(w.bagian?.['HEADLINE UTAMA'] || []).find((x) => x.emiten === e.emiten)?.judul || 'lihat catatan edisi ini'}`,
      teks: [e.emiten, 'emiten saham perusahaan'].join(' ').toLowerCase(),
      aksi: () => pindahHalaman('emiten'),
    });
  }

  for (const nama of Object.keys(w.bagian || {})) {
    const namaBersih = nama.split(' (')[0];
    idx.push({
      jenis: 'Bagian', kode: '',
      judul: namaBersih,
      teks: [namaBersih, 'bagian warta'].join(' ').toLowerCase(),
      aksi: () => pindahHalaman('warta'),
    });
  }

  return idx;
}

function tampilkanSaran(q) {
  const kotak = $('#orbit-saran');
  const input = $('#orbit-input');
  if (!kotak) return;

  const kueri = q.trim().toLowerCase();

  if (kueri.length < 2) {
    kotak.hidden = true;
    kotak.innerHTML = '';
    input.setAttribute('aria-expanded', 'false');
    return;
  }

  // Dua huruf pertama sudah memicu pencarian (sesuai konsep Orbit).
  const cocok = state.indeks.filter((e) => e.teks.includes(kueri)).slice(0, 12);

  if (!cocok.length) {
    kotak.innerHTML = `
      <div class="saran-kosong">
        Tidak ada hasil untuk <b>${esc(q)}</b>.<br>
        Coba kata yang lebih umum, misalnya nama emiten atau topik.
      </div>`;
    kotak.hidden = false;
    input.setAttribute('aria-expanded', 'true');
    return;
  }

  // Hasil dikelompokkan: Halaman, Berita, Emiten, Bagian.
  const urutan = ['Halaman', 'Berita', 'Emiten', 'Bagian'];
  const grup = new Map();
  for (const c of cocok) {
    if (!grup.has(c.jenis)) grup.set(c.jenis, []);
    grup.get(c.jenis).push(c);
  }

  let no = 0;
  kotak.innerHTML = urutan.filter((j) => grup.has(j)).map((j) => `
    <div class="saran-grup">${esc(j)}</div>
    ${grup.get(j).map((c) => {
      const i = no++;
      return `
        <button type="button" class="saran-item" role="option" data-saran="${i}">
          ${c.kode ? `<span class="saran-kode">${esc(c.kode)}</span>` : '<span class="saran-kode">—</span>'}
          <span class="saran-teks">${esc(c.judul || c.teks)}</span>
          <span class="saran-jenis">${esc(c.jenis)}</span>
        </button>`;
    }).join('')}
  `).join('');

  // Simpan daftar rata supaya indeks tombol cocok.
  const rata = [];
  for (const j of urutan) if (grup.has(j)) rata.push(...grup.get(j));
  kotak.dataset.jumlah = String(rata.length);

  $$('[data-saran]', kotak).forEach((b) => {
    b.addEventListener('click', () => {
      const c = rata[Number(b.dataset.saran)];
      if (!c) return;
      kotak.hidden = true;
      input.value = '';
      c.aksi();
    });
  });

  kotak.hidden = false;
  input.setAttribute('aria-expanded', 'true');
}

function siapkanOrbit(w) {
  const form = $('#orbit-cari');
  const input = $('#orbit-input');
  if (!form || !input) return;

  let timer;
  input.addEventListener('input', () => {
    clearTimeout(timer);
    timer = setTimeout(() => tampilkanSaran(input.value), 300);   // debounce 300ms
  });

  // Enter membuka halaman hasil lengkap; klik saran membuka target tepat.
  form.addEventListener('submit', (ev) => {
    ev.preventDefault();
    const q = input.value.trim();
    $('#orbit-saran').hidden = true;
    pindahHalaman('cari');
    const ic = $('#input-cari');
    if (ic) {
      ic.value = q;
      ic.dispatchEvent(new Event('input'));
    }
  });

  // Escape menutup saran tanpa menghapus teks.
  input.addEventListener('keydown', (ev) => {
    if (ev.key === 'Escape') {
      const kotak = $('#orbit-saran');
      if (kotak && !kotak.hidden) {
        kotak.hidden = true;
        input.setAttribute('aria-expanded', 'false');
      }
    }
  });

  // Klik di luar menutup saran.
  document.addEventListener('click', (ev) => {
    const kotak = $('#orbit-saran');
    if (!kotak || kotak.hidden) return;
    if (!form.contains(ev.target)) {
      kotak.hidden = true;
      input.setAttribute('aria-expanded', 'false');
    }
  });

  // Pintasan ⌘/Ctrl + K — label menyesuaikan sistem pengguna.
  // Menulis "⌘K" di Windows akan menyesatkan: tombol itu tidak ada.
  const pintasan = $('#orbit-pintasan');
  if (pintasan) {
    const mac = /Mac|iPhone|iPad/.test(navigator.platform || navigator.userAgent);
    pintasan.textContent = mac ? '⌘ K' : 'Ctrl K';
  }

  // Pintasan ⌘/Ctrl + K — terlihat di chip, bekerja di mana saja.
  document.addEventListener('keydown', (ev) => {
    if ((ev.metaKey || ev.ctrlKey) && ev.key.toLowerCase() === 'k') {
      ev.preventDefault();
      pindahHalaman('orbit');
      setTimeout(() => input.focus(), 80);
    }
  });

  // Chip saran — maksimal lima, kontekstual.
  const chipKotak = $('#orbit-chip');
  if (chipKotak) {
    const daftar = [
      { teks: 'Warta hari ini', aksi: () => pindahHalaman('warta') },
      { teks: 'Emiten edisi ini', aksi: () => pindahHalaman('emiten') },
      { teks: 'Jelajah', aksi: () => pindahHalaman('jelajah') },
      { teks: 'Kalender', aksi: () => pindahHalaman('kalender') },
      { teks: 'Arsip', aksi: () => pindahHalaman('arsip') },
    ];
    chipKotak.innerHTML = daftar.map((c, i) =>
      `<button type="button" class="chip" data-chip="${i}">${esc(c.teks)}</button>`).join('');
    $$('[data-chip]', chipKotak).forEach((b) => {
      b.addEventListener('click', () => daftar[Number(b.dataset.chip)].aksi());
    });
  }
}

function panelCaraMembaca() {
  bukaPanel('Cara membaca Ronce', `
    <p class="redup">Ronce bukan terminal trading dan bukan chatbot. Ia ruang
    editorial: masuk dari satu pertanyaan, temukan satu cerita, lalu telusuri
    sampai sumbernya.</p>

    <h3 style="margin:20px 0 8px;font-size:1rem">Urutan membaca</h3>
    <p class="kecil redup">Headline → konteks → bukti → sumber. Angka dan tabel
    tersedia satu tingkat lebih dalam, bukan di depan.</p>

    <h3 style="margin:20px 0 8px;font-size:1rem">Yang selalu disertakan</h3>
    <p class="kecil redup">Setiap edisi mencantumkan sumber, jendela waktu data,
    dan status penerbitan. Tidak ada angka yang berdiri sendiri.</p>

    <h3 style="margin:20px 0 8px;font-size:1rem">Yang belum dapat dibuktikan</h3>
    <p class="kecil redup">Kalau data tidak tersedia, Ronce mengatakannya terus
    terang — tidak mengisi kekosongan dengan angka karangan.</p>

    <h3 style="margin:20px 0 8px;font-size:1rem">Status data</h3>
    <p class="kecil redup">
      <span class="lencana aman">verified</span> sudah dikonfirmasi ·
      <span class="lencana info">confirmed</span> sumber jelas ·
      <span class="lencana netral">provisional</span> perlu dikonfirmasi
    </p>

    <p class="samar kecil" style="margin-top:20px">Pintasan: tekan ⌘/Ctrl + K
    untuk kembali ke textbox Orbit dari halaman mana pun.</p>
  `);
}


/* ---------------------------------------------------------------- render */

function renderStatistik(w) {
  const kotak = $('#stats');
  if (!kotak) return;

  // Ringkasan angka edisi dalam satu baris ringkas — bukan kotak besar.
  // Orbit harus tetap bersih, jadi angka-angka ini pindah ke halaman Warta.
  const semuaEntri = Object.values(w.bagian || {}).flat();
  const berita = (w.bagian?.['HEADLINE UTAMA'] || []).length || semuaEntri.length;
  const bagianTerisi = Object.values(w.bagian || {}).filter((v) => v.length).length;
  const posts = w.jumlah_post || (w.posts || []).length;
  const sumber = (w.sumber || []).length;

  const item = [
    [berita, 'berita utama'],
    [bagianTerisi, 'bagian terisi'],
    [posts, 'post siap terbit'],
    [sumber, 'sumber berbeda'],
  ];

  kotak.innerHTML = item.map(([n, label]) =>
    `<span><span class="meta-angka">${Number(n).toLocaleString('id-ID')}</span> ${esc(label)}</span>`
  ).join('');
}


function renderWarta(w) {
  const tabKotak = $('#warta-tab');
  const panelKotak = $('#warta-panel');
  if (!tabKotak) return;

  $('#warta-judul').textContent = w.judul || 'Warta';
  $('#warta-ringkas').textContent = w.ringkasan || '';

  const bagian = Object.entries(w.bagian || {}).filter(([, isi]) => isi.length);
  if (!bagian.length) {
    tabKotak.innerHTML = '';
    panelKotak.innerHTML = '<p class="redup">Belum ada isi pada edisi ini.</p>';
    return;
  }

  tabKotak.innerHTML = bagian.map(([nama], i) => `
    <button role="tab" aria-selected="${i === 0}" aria-controls="panel-${i}"
            id="tab-${i}" tabindex="${i === 0 ? 0 : -1}">${esc(nama)}</button>`).join('');

  panelKotak.innerHTML = bagian.map(([nama, isi], i) => `
    <div class="panel warta-bagian" data-bagian="${i}" id="panel-${i}" role="tabpanel" aria-labelledby="tab-${i}" ${i ? 'hidden' : ''}>
      <div class="kartu-grid">
        ${isi.map((e, j) => `
          <article class="kartu sorot-baris" data-entri="${i}-${j}" tabindex="0" role="button">
            <div class="baris-atas">
              ${e.emiten ? `<span class="kode">${esc(e.emiten)}</span>` : ''}
              ${e.media ? `<span class="lencana info">${esc(e.media)}</span>` : ''}
            </div>
            ${e.judul ? `<h3 class="kartu-judul">${esc(e.judul)}</h3>` : ''}
            <p>${esc(e.narasi || '')}</p>
          </article>`).join('')}
      </div>
    </div>`).join('');

  // Tab: klik dan panah kiri/kanan.
  $$('[role="tab"]', tabKotak).forEach((btn, i) => {
    btn.addEventListener('click', () => pilihTab(i));
    btn.addEventListener('keydown', (ev) => {
      const n = $$('[role="tab"]', tabKotak).length;
      if (ev.key === 'ArrowRight') { ev.preventDefault(); pilihTab((i + 1) % n); }
      if (ev.key === 'ArrowLeft') { ev.preventDefault(); pilihTab((i - 1 + n) % n); }
    });
  });

  // Sorotan "sedang dibaca": satu kartu menyala saat panel detailnya
  // dibuka, sisanya meredup tipis. Panah kiri/kanan untuk berpindah.
  const sorot = (el) => {
    const panel = el.closest('.warta-bagian');
    $$('.sorot-baris', panel).forEach((k) => k.removeAttribute('data-baca'));
    el.setAttribute('data-baca', '1');
    panel.setAttribute('data-ada-sorot', '1');
    panel.dataset.sorotIndex = [...$$('.sorot-baris', panel)].indexOf(el);
  };

  $$('[data-entri]', panelKotak).forEach((el) => {
    el.addEventListener('click', () => {
      const [i, j] = el.dataset.entri.split('-').map(Number);
      const e = bagian[i][1][j];
      const namaBagian = bagian[i][0].split(' (')[0];
      sorot(el);
      bukaPanel(e.emiten || namaBagian, `
        ${e.judul ? `<h3 style="margin-bottom:12px">${esc(e.judul)}</h3>` : ''}
        <p>${esc(e.narasi || '')}</p>
        ${e.media ? `<p class="samar kecil">Sumber: ${esc(e.media)}</p>` : ''}
        ${e.emiten ? `<p class="samar kecil">Emiten: <span class="mono">${esc(e.emiten)}</span></p>` : ''}
      `, {
        teks: `${e.emiten}|${e.judul || e.narasi || ''}`.slice(0, 200),
        kode: e.emiten || '',
        bagian: namaBagian,
        judul: e.judul || '',
        narasi: e.narasi || '',
      });
    });
    el.addEventListener('focus', () => sorot(el));
  });
}

function pilihTab(i) {
  $$('[role="tab"]').forEach((b, j) => {
    b.setAttribute('aria-selected', String(i === j));
    b.tabIndex = i === j ? 0 : -1;
    const p = $('#panel-' + j);
    if (p) p.hidden = i !== j;
    if (i === j) b.focus();
  });
}

function renderEmiten(w) {
  const tb = $('#tabel-emiten tbody');
  if (!tb) return;
  const peta = new Map();

  for (const [nama, isi] of Object.entries(w.bagian || {})) {
    for (const e of isi) {
      if (!e.emiten) continue;
      const r = peta.get(e.emiten) || { kode: e.emiten, cerita: 0, klaim: 0 };
      if (nama === 'HEADLINE UTAMA') r.cerita += 1;
      r.klaim += 1;
      peta.set(e.emiten, r);
    }
  }

  const baris = [...peta.values()].sort((a, b) => b.klaim - a.klaim);
  tb.innerHTML = baris.length ? baris.map((r) => `
    <tr>
      <td><span class="kode">${esc(r.kode)}</span></td>
      <td class="num">${r.cerita}</td>
      <td class="num">${r.klaim}</td>
      <td style="text-align:right"><button class="tombol" data-emiten="${esc(r.kode)}">Rincian</button></td>
    </tr>`).join('') : '<tr><td colspan="4" class="samar">Tidak ada emiten pada edisi ini.</td></tr>';

  $$('[data-emiten]', tb).forEach((b) => {
    b.addEventListener('click', () => {
      const kode = b.dataset.emiten;
      const rekam = [];
      for (const [nama, isi] of Object.entries(w.bagian || {})) {
        for (const e of isi) if (e.emiten === kode) rekam.push({ nama, ...e });
      }
      bukaPanel(kode, `
        <p class="samar kecil">${rekam.length} catatan pada edisi ini</p>
        ${rekam.map((e) => `
          <div style="margin-bottom:20px">
            <span class="lencana netral">${esc(e.nama)}</span>
            ${e.judul ? `<h3 style="margin:10px 0 8px;font-size:1rem">${esc(e.judul)}</h3>` : ''}
            <p class="kecil redup">${esc(e.narasi || '')}</p>
          </div>`).join('')}
      `);
    });
  });
}

/* ---------------------------------------------------------------- Jelajah
   Peta tema dua dimensi. Tokoh dan nama muncul di sini sebagai simpul,
   bukan sebagai halaman terpisah.

   Aturan: hanya tampilkan relasi yang benar-benar ada di data.
   Jangan menggambar garis "berita menyebabkan harga bergerak".

   Catatan: nama bagian (HEADLINE UTAMA, dst.) BUKAN tema. Ia dipakai
   sebagai asal-usul catatan, bukan simpul. Tema hanya diambil dari kata
   kunci isi berita supaya tidak ada dua hal berbeda yang tercampur. */

function bangunPeta(w) {
  const tema = new Map();   // nama tema -> { nama, emiten:Set, berita:[] }

  for (const [namaBagian, isi] of Object.entries(w.bagian || {})) {
    const bersih = namaBagian.split(' (')[0];
    for (const e of isi) {
      const t = (e.narasi || '').toLowerCase();
      const kunci = [];
      if (/dividen/.test(t)) kunci.push('Dividen');
      if (/rights issue|right issue|rights/.test(t)) kunci.push('Rights issue');
      if (/rups|rapat umum/.test(t)) kunci.push('RUPS');
      if (/buyback|beli kembali/.test(t)) kunci.push('Buyback');
      if (/kepemilikan|pemegang saham|melepas|mengurangi/.test(t)) kunci.push('Kepemilikan');

      for (const k of kunci) {
        if (!tema.has(k)) tema.set(k, { nama: k, emiten: new Set(), berita: [] });
        const T = tema.get(k);
        if (e.emiten) T.emiten.add(e.emiten);
        T.berita.push({
          emiten: e.emiten || '', judul: e.judul || '',
          narasi: e.narasi || '', bagian: bersih,
        });
      }
    }
  }

  // Nama tokoh sebagai simpul tersendiri — muncul di sini, bukan di halaman lain.
  const polaNama = /([A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,3})\s+(menambah|mengurangi|membeli|menjual|melepas)/;
  const tokoh = [];
  for (const isi of Object.values(w.bagian || {})) {
    for (const e of isi) {
      const m = (e.narasi || '').match(polaNama);
      if (m) tokoh.push({ nama: m[1], emiten: e.emiten || '', narasi: e.narasi || '', aksi: m[2] });
    }
  }

  // Bagian edisi dipakai sebagai pintasan, bukan sebagai tema.
  const bagian = Object.entries(w.bagian || {})
    .filter(([, v]) => v.length)
    .map(([n, v]) => ({ nama: n.split(' (')[0], jumlah: v.length }));

  return { tema: [...tema.values()].sort((a, b) => b.berita.length - a.berita.length), tokoh, bagian };
}

function renderJelajah(w) {
  const petaKotak = $('#jelajah-peta');
  const panel = $('#jelajah-panel');
  if (!petaKotak || !panel) return;

  const { tema, tokoh, bagian } = bangunPeta(w);

  if (!tema.length && !tokoh.length) {
    petaKotak.innerHTML = '<p class="redup">Belum ada tema pada edisi ini.</p>';
    return;
  }

  petaKotak.innerHTML = `
    ${tema.length ? `
      <div class="peta-grup">
        <span class="peta-label">Tema</span>
        ${tema.map((t, i) => `
          <button type="button" class="simpul" data-tema="${i}">
            <span class="simpul-nama">${esc(t.nama)}</span>
            <span class="simpul-jumlah">${t.berita.length}</span>
          </button>`).join('')}
      </div>` : ''}

    ${tokoh.length ? `
      <div class="peta-grup" style="margin-top:28px">
        <span class="peta-label">Nama yang tercatat</span>
        ${tokoh.map((t, i) => `
          <button type="button" class="simpul" data-orang="${i}">
            <span class="simpul-inisial">${esc(t.nama.split(' ').map((x) => x[0]).slice(0, 2).join('').toUpperCase())}</span>
            <span class="simpul-nama">${esc(t.nama)}</span>
            <span class="simpul-jumlah">${esc(t.emiten || '—')}</span>
          </button>`).join('')}
      </div>` : ''}

    ${bagian.length ? `
      <div class="peta-grup" style="margin-top:28px">
        <span class="peta-label">Bagian edisi ini</span>
        ${bagian.map((b, i) => `
          <button type="button" class="simpul" data-bagian="${i}">
            <span class="simpul-nama">${esc(b.nama)}</span>
            <span class="simpul-jumlah">${b.jumlah}</span>
          </button>`).join('')}
      </div>` : ''}`;

  const tampilTema = (i) => {
    const t = tema[i];
    panel.innerHTML = `
      <span class="label">Tema</span>
      <h3>${esc(t.nama)}</h3>
      <p class="kecil redup">Muncul pada ${t.berita.length} catatan edisi ini.</p>

      <h4 class="panel-sub">Emiten terkait</h4>
      <p class="kecil">${[...t.emiten].map((s) => `<span class="kode">${esc(s)}</span>`).join(' ') || '<span class="samar">tidak ada</span>'}</p>

      <h4 class="panel-sub">Catatan</h4>
      <div class="peta-catatan">
        ${t.berita.slice(0, 6).map((b, j) => `
          <button type="button" class="peta-item" data-catatan="${j}">
            ${b.emiten ? `<span class="kode">${esc(b.emiten)}</span>` : ''}
            <span class="peta-judul">${esc(b.judul || (b.narasi || '').slice(0, 80))}</span>
          </button>`).join('')}
      </div>
      <p class="samar kecil" style="margin-top:16px">Relasi: catatan ini menyebut
      emiten tersebut di atas. Ronce tidak menyimpulkan sebab-akibat.</p>`;

    $$('[data-catatan]', panel).forEach((b) => {
      b.addEventListener('click', () => {
        const c = t.berita[Number(b.dataset.catatan)];
        bukaPanel(c.emiten || t.nama, `
          <span class="lencana netral">${esc(c.bagian)}</span>
          ${c.judul ? `<h3 style="margin:12px 0 10px">${esc(c.judul)}</h3>` : ''}
          <p>${esc(c.narasi)}</p>`);
      });
    });
  };

  const tampilOrang = (i) => {
    const o = tokoh[i];
    panel.innerHTML = `
      <span class="label">Nama tercatat</span>
      <h3>${esc(o.nama)}</h3>
      <p class="kecil redup">Tercatat di keterbukaan informasi edisi ini.</p>
      ${o.emiten ? `<p class="kecil" style="margin-top:12px">Terkait: <span class="kode">${esc(o.emiten)}</span></p>` : ''}
      <p style="margin-top:14px">${esc(o.narasi)}</p>
      <p class="samar kecil" style="margin-top:16px">Foto belum tersedia. Ronce menampilkan
      inisial daripada memakai foto yang tidak terbukti hak pakainya.</p>`;
  };

  $$('[data-tema]', petaKotak).forEach((b) => {
    b.addEventListener('click', () => {
      $$('.simpul', petaKotak).forEach((x) => x.removeAttribute('aria-pressed'));
      b.setAttribute('aria-pressed', 'true');
      tampilTema(Number(b.dataset.tema));
    });
  });

  $$('[data-orang]', petaKotak).forEach((b) => {
    b.addEventListener('click', () => {
      $$('.simpul', petaKotak).forEach((x) => x.removeAttribute('aria-pressed'));
      b.setAttribute('aria-pressed', 'true');
      tampilOrang(Number(b.dataset.orang));
    });
  });

  $$('[data-bagian]', petaKotak).forEach((b) => {
    b.addEventListener('click', () => {
      $$('.simpul', petaKotak).forEach((x) => x.removeAttribute('aria-pressed'));
      b.setAttribute('aria-pressed', 'true');
      const nama = bagian[Number(b.dataset.bagian)].nama;
      const isi = (w.bagian || {})[Object.keys(w.bagian).find((k) => k.startsWith(nama))] || [];
      panel.innerHTML = `
        <span class="label">Bagian edisi</span>
        <h3>${esc(nama)}</h3>
        <p class="kecil redup">${isi.length} catatan pada edisi ini.</p>
        <div class="peta-catatan" style="margin-top:16px">
          ${isi.map((e, j) => `
            <button type="button" class="peta-item" data-bagain="${j}">
              ${e.emiten ? `<span class="kode">${esc(e.emiten)}</span>` : ''}
              <span class="peta-judul">${esc(e.judul || (e.narasi || '').slice(0, 70))}</span>
            </button>`).join('')}
        </div>`;

      $$('[data-bagain]', panel).forEach((x) => {
        x.addEventListener('click', () => {
          const c = isi[Number(x.dataset.bagain)];
          bukaPanel(c.emiten || nama, `
            <span class="lencana netral">${esc(nama)}</span>
            ${c.judul ? `<h3 style="margin:12px 0 10px">${esc(c.judul)}</h3>` : ''}
            <p>${esc(c.narasi)}</p>`);
        });
      });
    });
  });
}

/* ---------------------------------------------------------------- Disimpan
   Penanda bacaan lokal. Bukan portofolio, bukan watchlist trading. */
const KUNCI_SIMPAN = 'ronce-disimpan';

function bacaSimpanan() {
  try {
    const t = localStorage.getItem(KUNCI_SIMPAN);
    const d = t ? JSON.parse(t) : [];
    return Array.isArray(d) ? d : [];
  } catch (e) { return []; }
}

function tulisSimpanan(d) {
  try { localStorage.setItem(KUNCI_SIMPAN, JSON.stringify(d)); } catch (e) { /* diabaikan */ }
}

function sudahDisimpan(teks) {
  return bacaSimpanan().some((x) => x.teks === teks);
}

function togolSimpan(item) {
  const d = bacaSimpanan();
  const i = d.findIndex((x) => x.teks === item.teks);
  if (i >= 0) d.splice(i, 1);
  else d.unshift({ ...item, waktu: new Date().toISOString() });
  tulisSimpanan(d.slice(0, 60));
  return i < 0;
}

function renderDisimpan(w) {
  const kotak = $('#disimpan-isi');
  if (!kotak) return;

  const d = bacaSimpanan();
  if (!d.length) {
    kotak.innerHTML = `
      <div class="catatan">
        <b>Belum ada yang disimpan.</b>
        Buka rincian mana pun, lalu tekan <b>Simpan</b> untuk menandainya.
        Penanda ini disimpan di peramban kamu sendiri, tidak dikirim ke mana pun.
      </div>`;
    return;
  }

  kotak.innerHTML = `<div class="simpan-grid">${d.map((x, i) => `
    <article class="kartu" data-simpan="${i}" tabindex="0" role="button">
      <div class="baris-atas">
        ${x.kode ? `<span class="kode">${esc(x.kode)}</span>` : ''}
        <span class="lencana netral">${esc(x.bagian || 'tersimpan')}</span>
      </div>
      <h3>${esc(x.judul || x.teks.slice(0, 70))}</h3>
      <p>${esc((x.narasi || '').slice(0, 150))}</p>
      <div class="simpan-kaki">
        <span class="samar kecil">${esc((x.waktu || '').slice(0, 10))}</span>
        <button type="button" class="tombol kecil" data-hapus="${i}">Hapus</button>
      </div>
    </article>`).join('')}</div>`;

  $$('[data-hapus]', kotak).forEach((b) => {
    b.addEventListener('click', (ev) => {
      ev.stopPropagation();
      const d2 = bacaSimpanan();
      d2.splice(Number(b.dataset.hapus), 1);
      tulisSimpanan(d2);
      renderDisimpan(w);
    });
  });

  $$('[data-simpan]', kotak).forEach((el) => {
    el.addEventListener('click', () => {
      const x = d[Number(el.dataset.simpan)];
      bukaPanel(x.kode || x.judul || 'Tersimpan', `
        <span class="lencana netral">${esc(x.bagian || 'tersimpan')}</span>
        ${x.judul ? `<h3 style="margin:12px 0 10px">${esc(x.judul)}</h3>` : ''}
        <p>${esc(x.narasi || '')}</p>`);
    });
  });
}

/* ---------------------------------------------------------------- Kalender
   Agenda ke depan: aksi korporasi dan RUPS dari Sectors.
   Bentuknya timeline editorial yang bisa digeser per tanggal, sesuai
   ide awal. Bukan kalender kotak 7x5, bukan arsip.

   Semua isi berasal dari agenda.json yang dibuat ronce.py. Kalau kosong,
   Ronce mengatakannya kosong. */

let KALENDER = { data: null, geser: 0, hari: null, paksaSemua: false };

const NAMA_HARI = ['Min', 'Sen', 'Sel', 'Rab', 'Kam', 'Jum', 'Sab'];
const NAMA_BULAN = ['Januari', 'Februari', 'Maret', 'April', 'Mei', 'Juni',
                    'Juli', 'Agustus', 'September', 'Oktober', 'November', 'Desember'];

/* Format tanggal LOKAL (YYYY-MM-DD).
   Jangan pakai toISOString(): itu UTC, jadi di WIB (UTC+7) tanggal
   bisa bergeser satu hari dan penanda kalender tidak cocok dengan
   isi yang ditampilkan. */
function isoLokal(d) {
  const th = d.getFullYear();
  const bl = String(d.getMonth() + 1).padStart(2, '0');
  const tg = String(d.getDate()).padStart(2, '0');
  return `${th}-${bl}-${tg}`;
}


/* Kumpulkan semua agenda jadi satu daftar datar.
   Satu agenda bisa punya BEBERAPA tanggal (mis. RUPS punya tanggal
   pencatatan dan tanggal rapat). Untuk timeline, tiap tanggal penting
   dijadikan baris tersendiri supaya tidak ada informasi yang hilang —
   sebelumnya hanya tanggal pertama yang dipakai, sehingga label
   "pencatatan" muncul berulang tanpa penjelasan. */
function ratakanAgenda(data) {
  const baris = [];
  for (const [jenis, isi] of Object.entries(data || {})) {
    if (jenis.startsWith('_') || !isi || !Array.isArray(isi.agenda)) continue;
    for (const a of isi.agenda) {
      for (const t of (a.tanggal || [])) {
        baris.push({
          jenis,
          namaJenis: isi.nama || jenis,
          simbol: a.simbol || '',
          tanggal: t.tanggal,
          labelTanggal: t.label,
          semuaTanggal: a.tanggal || [],
          keterangan: a.keterangan || '',
          angka: a.angka || {},
        });
      }
    }
  }
  baris.sort((a, b) => a.tanggal.localeCompare(b.tanggal)
    || a.simbol.localeCompare(b.simbol));
  return baris;
}

/* Nama label tanggal yang bisa dibaca orang, bukan istilah bursa mentah. */
const LABEL_TANGGAL = {
  'pencatatan': 'batas daftar pemegang saham',
  'agm': 'rapat',
  'cum': 'batas akhir beli',
  'ex': 'mulai tanpa hak',
  'record': 'pencatatan',
  'rapat': 'rapat',
  'pengumuman': 'pengumuman',
  'pembayaran': 'pembayaran',
  'mulai perdagangan': 'mulai diperdagangkan',
  'akhir perdagangan': 'akhir diperdagangkan',
  'penebusan': 'penebusan',
};

function labelEnak(label) {
  return LABEL_TANGGAL[String(label).toLowerCase()] || label;
}

/* Kalimat penjelas per JENIS TANGGAL, bukan cuma jenis agenda.
   Data Sectors tidak memuat judul atau lokasi RUPS, jadi Ronce tidak
   bisa mengarang isinya. Yang bisa dilakukan: jelaskan apa arti
   tanggal itu bagi pembaca. Itu sudah cukup berbeda antar baris. */
function penjelasanAgenda(a) {
  if (a.keterangan) return a.keterangan;

  const angka = angkaEnak(a.angka);
  const jenis = a.jenis;
  const label = String(a.labelTanggal || '').toLowerCase();

  if (jenis === 'agm') {
    if (label === 'rapat') {
      return 'Hari rapatnya. Pemegang saham memutuskan hal-hal yang diajukan direksi.';
    }
    if (label === 'pencatatan' || label === 'record') {
      return 'Hari terakhir membeli saham supaya tercatat sebagai pemegang saham yang berhak ikut rapat.';
    }
    return 'Jadwal yang tercatat untuk RUPS ini.';
  }

  if (jenis === 'right_issue') {
    if (label === 'cum') return 'Hari terakhir membeli saham supaya berhak ikut rights issue.';
    if (label === 'ex') return 'Sejak hari ini, saham yang dibeli tidak lagi berhak ikut rights issue.';
    if (label === 'pencatatan' || label === 'record') return 'Pencatatan daftar pemegang saham yang berhak.';
    if (label === 'mulai perdagangan') return 'Saham baru mulai diperdagangkan di bursa.';
    if (label === 'akhir perdagangan') return 'Hari terakhir saham baru diperdagangkan.';
    if (label === 'penebusan') return 'Hari terakhir menebus saham baru.';
    return angka ? `Rights issue dengan ${angka}.` : 'Jadwal rights issue.';
  }

  if (jenis === 'dividend' || jenis === 'upcoming_dividend') {
    if (label === 'cum') return 'Hari terakhir membeli saham supaya berhak menerima dividen.';
    if (label === 'ex') return 'Sejak hari ini, saham yang dibeli tidak lagi berhak atas dividen ini.';
    if (label === 'pencatatan' || label === 'record') return 'Pencatatan siapa saja yang berhak menerima dividen.';
    if (label === 'pembayaran') return 'Hari dividen dibayarkan ke rekening pemegang saham.';
    if (label === 'pengumuman') return 'Hari rencana dividen ini diumumkan ke bursa.';
    return angka ? `Dividen ${angka}.` : 'Jadwal pembagian dividen.';
  }

  if (jenis === 'stock_split') return angka ? `Pemecahan saham, ${angka}.` : 'Pemecahan nilai nominal saham.';
  if (jenis === 'bonus') return angka ? `Saham bonus, ${angka}.` : 'Pembagian saham bonus.';
  if (jenis === 'warrant') return 'Jadwal waran.';

  return angka || 'Jadwal yang tercatat di Sectors.';
}

function tanggalIndo(iso) {
  const d = new Date(iso + 'T00:00:00');
  if (isNaN(d)) return iso;
  return `${d.getDate()} ${NAMA_BULAN[d.getMonth()]} ${d.getFullYear()}`;
}

function angkaEnak(angka) {
  // Tampilkan angka dari data apa adanya, dengan nama yang bisa dibaca.
  const nama = {
    price: 'harga', dividend_amount: 'dividen per saham',
    old_ratio: 'rasio lama', new_ratio: 'rasio baru',
    value: 'nilai', amount: 'jumlah',
  };
  const bagian = [];
  for (const [k, v] of Object.entries(angka || {})) {
    if (typeof v !== 'number') continue;
    bagian.push(`${nama[k] || k.replace(/_/g, ' ')} ${v.toLocaleString('id-ID')}`);
  }
  return bagian.join(' · ');
}

/* Gambar kalender dengan pola spine + panggung.

   Spine di kiri berisi daftar TANGGAL YANG PUNYA AGENDA saja, bukan
   21 hari kosong. Ini mengikuti pola shapeofintelligence: daftar item
   yang bermakna, bukan kalender grid yang penuh titik. Tanggal aktif
   menyala seperti bintang.

   Panggung di kanan menampilkan isi tanggal terpilih — bagian yang
   di-highlight. */
function gambarKalender() {
  const nav = $('#kalender-navigasi');
  const spine = $('#kalender-spine');
  const kotak = $('#kalender-isi');
  if (!nav || !spine || !kotak) return;

  const semua = KALENDER.data;

  if (!semua || !semua.length) {
    nav.innerHTML = '';
    spine.innerHTML = '';
    kotak.innerHTML = `
      <div class="catatan peringatan">
        <b>Belum ada agenda.</b>
        Sectors tidak mengembalikan jadwal aksi korporasi atau RUPS untuk
        rentang ke depan. Sistem tidak mengisi kekosongan dengan jadwal
        karangan. Coba jalankan <span class="mono">python ronce.py make</span>
        untuk menarik agenda terbaru.
      </div>`;
    return;
  }

  // Kumpulkan tanggal unik yang punya agenda, urut.
  const petaTanggal = new Map();
  for (const a of semua) {
    if (!petaTanggal.has(a.tanggal)) petaTanggal.set(a.tanggal, []);
    petaTanggal.get(a.tanggal).push(a);
  }
  const daftarTanggal = [...petaTanggal.keys()].sort();

  // Rentang yang ditampilkan: 21 hari dari agenda pertama.
  const HARI_TAMPIL = 21;
  const mulai = KALENDER.geser;
  const maksGeser = Math.max(0, daftarTanggal.length - 1);

  // Tanggal yang masuk rentang tampilan.
  const acuan = new Date(daftarTanggal[0] + 'T00:00:00');
  acuan.setDate(acuan.getDate() + mulai);
  const batas = new Date(acuan);
  batas.setDate(batas.getDate() + HARI_TAMPIL);

  const dalamRentang = daftarTanggal.filter((t) => {
    const d = new Date(t + 'T00:00:00');
    return d >= acuan && d < batas;
  });

  // Tanggal terpilih: yang disimpan, atau tanggal pertama dalam rentang.
  let terpilih = KALENDER.hari;
  if (KALENDER.paksaSemua) terpilih = '__semua__';
  else if (!terpilih || !dalamRentang.includes(terpilih)) {
    terpilih = dalamRentang[0] || daftarTanggal[0];
  }

  // ---- kepala: rentang + tombol geser ----
  const akhirRentang = new Date(acuan);
  akhirRentang.setDate(akhirRentang.getDate() + HARI_TAMPIL - 1);

  nav.innerHTML = `
    <button class="kalender-geser" id="kal-mundur" type="button" aria-label="Rentang sebelumnya"
            ${mulai <= 0 ? 'disabled' : ''}>
      <svg viewBox="0 0 24 24"><path d="m15 18-6-6 6-6"/></svg>
    </button>
    <button class="kalender-geser" id="kal-maju" type="button" aria-label="Rentang berikutnya"
            ${mulai >= maksGeser ? 'disabled' : ''}>
      <svg viewBox="0 0 24 24"><path d="m9 18 6-6-6-6"/></svg>
    </button>
    <span class="kalender-rentang">${tanggalIndo(isoLokal(acuan))} — ${tanggalIndo(isoLokal(akhirRentang))}</span>
    <button class="tombol kecil" id="kal-semuanya" type="button">
      ${KALENDER.paksaSemua ? 'Kembali ke tanggal' : `Lihat semua (${semua.length})`}
    </button>`;

  // ---- spine: daftar tanggal ----
  const barisSpine = [];

  // Item pertama: semua agenda — seperti "All Planets" di referensi.
  barisSpine.push(`
    <button type="button" class="spine-hari" data-semua="1"
            aria-pressed="${terpilih === '__semua__'}" data-ada="1">
      <span class="spine-titik" aria-hidden="true"></span>
      <span class="spine-tanggal">Semua agenda</span>
      <span class="spine-jumlah">${semua.length}</span>
    </button>`);

  for (const t of dalamRentang) {
    const d = new Date(t + 'T00:00:00');
    const isi = petaTanggal.get(t);
    const aktif = t === terpilih;
    barisSpine.push(`
      <button type="button" class="spine-hari" data-tanggal="${esc(t)}"
              aria-pressed="${aktif}" data-ada="1">
        <span class="spine-titik" aria-hidden="true"></span>
        <span class="spine-tanggal">${NAMA_HARI[d.getDay()]}, ${d.getDate()}</span>
        <span class="spine-bulan">${NAMA_BULAN[d.getMonth()].slice(0, 3)}</span>
        <span class="spine-jumlah">${isi.length}</span>
      </button>`);
  }

  if (dalamRentang.length < daftarTanggal.length) {
    barisSpine.push(`
      <button type="button" class="spine-hari" id="spine-lagi" data-ada="0">
        <span class="spine-titik" aria-hidden="true"></span>
        <span class="spine-tanggal">+${daftarTanggal.length - dalamRentang.length} tanggal lagi</span>
      </button>`);
  }

  spine.innerHTML = barisSpine.join('');

  // ---- panggung: isi tanggal terpilih ----
  const tampil = terpilih === '__semua__' ? semua : (petaTanggal.get(terpilih) || []);

  const grup = new Map();
  for (const a of tampil) {
    if (!grup.has(a.jenis)) grup.set(a.jenis, { nama: a.namaJenis, isi: [] });
    grup.get(a.jenis).isi.push(a);
  }

  const kepala = terpilih === '__semua__'
    ? `<span class="panggung-tanggal">Semua agenda</span>
       <span class="panggung-catatan">${semua.length} jadwal dari ${daftarTanggal.length} tanggal,
       ${tanggalIndo(daftarTanggal[0])} sampai ${tanggalIndo(daftarTanggal[daftarTanggal.length - 1])}.</span>`
    : `<span class="panggung-tanggal">${tanggalIndo(terpilih)}</span>
       <span class="panggung-catatan">${tampil.length} jadwal tercatat pada tanggal ini.</span>`;

  // Kaki panggung: dua tanggal berikutnya yang punya agenda.
  // Memberi jalan lanjut tanpa harus kembali ke spine.
  const idxKini = daftarTanggal.indexOf(terpilih);
  const berikutnya = idxKini >= 0 ? daftarTanggal.slice(idxKini + 1, idxKini + 3) : [];

  const kaki = berikutnya.length ? `
    <div class="panggung-lanjut">
      <span class="label-kecil">Tanggal berikutnya</span>
      <div class="panggung-lanjut-baris">
        ${berikutnya.map((t) => `
          <button type="button" class="pil-tanggal" data-pil="${esc(t)}">
            ${tanggalIndo(t)}
            <span class="jumlah">${(petaTanggal.get(t) || []).length}</span>
          </button>`).join('')}
      </div>
    </div>` : '';

  kotak.innerHTML = `
    <div class="panggung-kepala">${kepala}</div>
    ${[...grup.values()].map((g) => `
      <div class="agenda-grup">
        <div class="agenda-grup-kepala">
          <h3>${esc(g.nama)}</h3>
          <span class="jumlah">${g.isi.length} jadwal</span>
        </div>
        ${g.isi.map((a, i) => `
          <button type="button" class="agenda-item" data-agenda="${esc(a.simbol)}|${i}|${esc(g.nama)}">
            <span class="agenda-isi">
              <h4>
                ${a.simbol ? `<span class="kode">${esc(a.simbol)}</span>` : ''}
                ${esc(g.nama)}
                <span class="label-tanggal">${esc(labelEnak(a.labelTanggal))}</span>
              </h4>
              <p>${esc(penjelasanAgenda(a))}</p>
            </span>
            <span class="agenda-panah" aria-hidden="true">›</span>
          </button>`).join('')}
      </div>`).join('')}
    ${kaki}`;

  // ---- ikatan ----
  $('#kal-mundur')?.addEventListener('click', () => {
    KALENDER.geser = Math.max(0, KALENDER.geser - HARI_TAMPIL);
    KALENDER.hari = null;
    KALENDER.paksaSemua = false;
    gambarKalender();
  });
  $('#kal-maju')?.addEventListener('click', () => {
    KALENDER.geser = Math.min(maksGeser, KALENDER.geser + HARI_TAMPIL);
    KALENDER.hari = null;
    KALENDER.paksaSemua = false;
    gambarKalender();
  });
  $('#kal-semuanya')?.addEventListener('click', () => {
    KALENDER.paksaSemua = !KALENDER.paksaSemua;
    gambarKalender();
  });

  $$('[data-tanggal]', spine).forEach((b) => {
    b.addEventListener('click', () => {
      KALENDER.hari = b.dataset.tanggal;
      KALENDER.paksaSemua = false;
      gambarKalender();
    });
  });
  $('[data-semua]', spine)?.addEventListener('click', () => {
    KALENDER.paksaSemua = true;
    gambarKalender();
  });
  $('#spine-lagi')?.addEventListener('click', () => {
    KALENDER.geser = Math.min(maksGeser, KALENDER.geser + HARI_TAMPIL);
    KALENDER.hari = null;
    KALENDER.paksaSemua = false;
    gambarKalender();
  });

  // ---- pil tanggal berikutnya di kaki panggung ----
  $$('[data-pil]', kotak).forEach((b) => {
    b.addEventListener('click', () => {
      KALENDER.hari = b.dataset.pil;
      KALENDER.paksaSemua = false;
      gambarKalender();
    });
  });

  // ---- klik agenda: rincian lengkap dengan semua tanggalnya ----
  $$('[data-agenda]', kotak).forEach((b) => {
    b.addEventListener('click', () => {
      const [simbol, , namaGrup] = b.dataset.agenda.split('|');
      const a = tampil.find((x) => x.simbol === simbol && x.namaJenis === namaGrup);
      if (!a) return;
      bukaPanel(simbol || a.namaJenis, `
        <span class="lencana netral">${esc(a.namaJenis)}</span>
        ${simbol ? `<p class="kecil redup" style="margin-top:12px">Emiten: <span class="kode">${esc(simbol)}</span></p>` : ''}
        <h3 style="margin:16px 0 10px;font-size:1rem">Jadwal tercatat</h3>
        <dl class="profil-daftar" style="margin-top:0">
          ${a.semuaTanggal.map((t) => `
            <div class="profil-baris">
              <dt>${esc(labelEnak(t.label))}</dt>
              <dd>${esc(tanggalIndo(t.tanggal))}</dd>
            </div>`).join('')}
        </dl>
        ${angkaEnak(a.angka) ? `<p class="kecil redup" style="margin-top:16px">${esc(angkaEnak(a.angka))}</p>` : ''}
        ${a.keterangan ? `<p style="margin-top:14px">${esc(a.keterangan)}</p>` : ''}
        <p class="samar kecil" style="margin-top:18px">Sumber: Sectors. Jadwal bisa
        berubah; periksa pengumuman resmi emiten sebelum mengambil keputusan.</p>`);
    });
  });

  // ---- daftar lengkap di bawah timeline ----
  const daftar = $('#kalender-daftar');
  if (daftar) {
    daftar.innerHTML = `
      <div class="daftar-kepala">
        <h3>Seluruh jadwal</h3>
        <span class="jumlah">${semua.length} agenda · ${daftarTanggal.length} tanggal</span>
      </div>
      <p class="daftar-catatan">
        Semua agenda yang tercatat di Sectors, urut dari yang paling dekat.
        Klik baris untuk melihat seluruh tanggal agenda tersebut.
      </p>
      <table class="tabel-agenda">
        <thead>
          <tr>
            <th>Tanggal</th>
            <th>Jenis</th>
            <th>Emiten</th>
            <th>Tahap</th>
          </tr>
        </thead>
        <tbody>
          ${semua.map((a, idx) => `
            <tr data-baris="${idx}">
              <td class="kol-tanggal">
                ${tanggalIndo(a.tanggal)}
                <span class="label-kecil">${NAMA_HARI[new Date(a.tanggal + 'T00:00:00').getDay()]}</span>
              </td>
              <td class="kol-jenis">${esc(a.namaJenis)}</td>
              <td class="kol-emiten">${a.simbol ? `<span class="kode">${esc(a.simbol)}</span>` : '—'}</td>
              <td>${esc(labelEnak(a.labelTanggal))}</td>
            </tr>`).join('')}
        </tbody>
      </table>`;

    $$('[data-baris]', daftar).forEach((tr) => {
      tr.addEventListener('click', () => {
        const a = semua[Number(tr.dataset.baris)];
        if (!a) return;
        KALENDER.hari = a.tanggal;
        KALENDER.paksaSemua = false;
        gambarKalender();
        // Bawa pengguna kembali ke panggung supaya perubahan terlihat.
        $('#kalender-isi')?.scrollIntoView({ behavior: 'smooth', block: 'center' });
      });
    });
  }
}


async function renderKalender() {
  const kotak = $('#kalender-isi');
  if (!kotak) return;

  let data = null;
  try {
    const r = await fetch('agenda.json', { cache: 'no-store' });
    if (r.ok) data = await r.json();
  } catch (e) { /* diabaikan */ }

  KALENDER = { data: ratakanAgenda(data), geser: 0, hari: null, paksaSemua: false };

  gambarKalender();
}

function renderKalenderRingkas(w) {
  // Dipakai kalau agenda.json tidak tersedia: pakai aksi korporasi
  // dan RUPS dari Warta harian supaya halaman tidak kosong melompong.
  const aksi = (w.bagian?.['AKSI KORPORASI'] || []);
  const rups = (w.bagian?.['RUPS'] || []);
  return [...aksi.map((e) => ({ ...e, nama: 'Aksi korporasi' })),
          ...rups.map((e) => ({ ...e, nama: 'RUPS' }))];
}

/* ---------------------------------------------------------------- interaktif
   Tambahan sesuai permintaan: React Bits (Shiny Text, Magnetic, Tilt,
   Click Spark, Marquee), pita harga, dan progres baca,
   dan bagian "Yang belum dapat dibuktikan". */

/* ---- react bits: kilau judul ----
   Satu momen saja saat halaman dimuat: sapaan Orbit berkilau sekali.
   Sesuai prinsip "spend your boldness in one place" — sisanya tenang. */
function pasangKilau() {
  if (KURANGI_GERAK) return;
  const judul = $('#orbit-sapa');
  if (judul) judul.classList.add('kilau');
}

/* ---- react bits: tombol magnetik ---- */
function pasangMagnetik() {
  if (KURANGI_GERAK) return;
  $$('.tombol, .orbit-kirim').forEach((b) => {
    if (b.dataset.magnetik) return;
    b.dataset.magnetik = '1';
    b.classList.add('magnetik');
    b.addEventListener('pointermove', (ev) => {
      const r = b.getBoundingClientRect();
      const dx = (ev.clientX - (r.left + r.width / 2)) * 0.18;
      const dy = (ev.clientY - (r.top + r.height / 2)) * 0.18;
      b.style.transform = `translate(${dx.toFixed(1)}px, ${dy.toFixed(1)}px)`;
    });
    b.addEventListener('pointerleave', () => { b.style.transform = ''; });
  });
}

/* ---- react bits: kartu miring mengikuti kursor ----
   Tilt memakai transform inline, jadi ia menggantikan transform hover CSS
   selama kursor berada di atas kartu. Karena tilt sendiri sudah menyertakan
   translateY(-2px), efek terangkat saat hover tetap terasa. Saat kursor
   keluar, transform inline dihapus dan gaya CSS berlaku lagi. */
function pasangTilt() {
  if (KURANGI_GERAK) return;
  $$('.kartu').forEach((k) => {
    if (k.dataset.miring) return;
    k.dataset.miring = '1';
    k.classList.add('miring');
    k.addEventListener('pointermove', (ev) => {
      const r = k.getBoundingClientRect();
      const px = (ev.clientX - r.left) / r.width - 0.5;
      const py = (ev.clientY - r.top) / r.height - 0.5;
      k.style.transform =
        `perspective(760px) rotateX(${(-py * 3.2).toFixed(2)}deg) ` +
        `rotateY(${(px * 3.2).toFixed(2)}deg) translateY(-2px)`;
    });
    k.addEventListener('pointerleave', () => { k.style.transform = ''; });
  });
}

/* ---- react bits: percikan saat klik ---- */
function percikan(x, y) {
  if (KURANGI_GERAK) return;
  const jumlah = 6;
  for (let i = 0; i < jumlah; i++) {
    const p = document.createElement('span');
    p.className = 'percikan';
    const sudut = (Math.PI * 2 * i) / jumlah + Math.random() * 0.5;
    const jarak = 22 + Math.random() * 16;
    p.style.left = x + 'px';
    p.style.top = y + 'px';
    p.style.setProperty('--dx', (Math.cos(sudut) * jarak).toFixed(1) + 'px');
    p.style.setProperty('--dy', (Math.sin(sudut) * jarak).toFixed(1) + 'px');
    document.body.appendChild(p);
    setTimeout(() => p.remove(), 600);
  }
}

function pasangPercikan() {
  if (KURANGI_GERAK) return;
  document.addEventListener('pointerdown', (ev) => {
    // Hanya untuk elemen yang memang bisa ditekan.
    const sasaran = ev.target.closest('.kartu, .simpul, .tombol, .chip, .nav-item');
    if (sasaran) percikan(ev.clientX, ev.clientY);
  }, { passive: true });
}

/* ---- progres baca ---- */
function pasangProgres() {
  const batang = $('#progres span');
  if (!batang) return;
  const perbarui = () => {
    const h = document.documentElement;
    const bisa = h.scrollHeight - h.clientHeight;
    const porsi = bisa > 0 ? (h.scrollTop / bisa) : 0;
    batang.style.width = (Math.min(1, Math.max(0, porsi)) * 100).toFixed(1) + '%';
  };
  window.addEventListener('scroll', perbarui, { passive: true });
  window.addEventListener('resize', perbarui);
  perbarui();
}

/* ---- galat kepercayaan ---- */
function renderGalat(w) {
  const isi = $('#galat-isi');
  const tombol = $('#galat-tombol');
  if (!isi || !tombol) return;

  const jendela = w.jendela || [];
  const bagianKosong = Object.entries(w.bagian || {})
    .filter(([, v]) => !v.length).map(([n]) => n.split(' (')[0]);

  const catatan = [];

  catatan.push({
    teks: `Edisi ini <b>belum diterbitkan otomatis</b> — status mesin
           <span class="mono">publishable: ${esc(String(w.publishable ?? false))}</span>.
           Sistem menunggu persetujuan editor sebelum apa pun tayang.`,
    sumber: 'editor_approval: ' + esc(String(w.editor_approval || '—')) +
            ' · tulis API: ' + esc(String(w.api_write ?? false)),
  });

  if (jendela.length === 2) {
    catatan.push({
      teks: `Data hanya mencakup jendela <b>${esc(jendela[0])}</b> sampai <b>${esc(jendela[1])}</b>.
             Peristiwa di luar rentang itu tidak ikut dinilai.`,
      sumber: 'jendela pengambilan data',
    });
  }

  if (bagianKosong.length) {
    catatan.push({
      teks: `Bagian berikut kosong pada edisi ini: <b>${esc(bagianKosong.join(', '))}</b>.
             Kosong berarti tidak ada catatan pada jendela waktu tersebut — bukan data yang disembunyikan.`,
      sumber: 'pemeriksaan bagian',
    });
  } else {
    catatan.push({
      teks: 'Semua lima bagian terisi pada edisi ini.',
      sumber: 'pemeriksaan bagian',
    });
  }

  // Harga: sebutkan tanggal datanya supaya tidak disangka hari ini.
  const sorotan = Object.keys(w.bagian || {}).find((n) => n.startsWith('SOROTAN EMITEN'));
  if (sorotan) {
    const tgl = (sorotan.match(/data ([^)]+)\)/) || [])[1] || '';
    catatan.push({
      teks: `Angka harga pada bagian sorotan berasal dari <b>${esc(tgl || 'tanggal yang tertera di judul bagian')}</b>,
             bukan harga hari ini. Judul bagian selalu menyebut tanggalnya.`,
      sumber: 'sorotan emiten · ' + esc(tgl),
    });
  }

  catatan.push({
    teks: 'Narasi ditulis ulang oleh model bahasa dari berita dan keterbukaan informasi. '
        + 'Setiap angka tetap harus diperiksa pada sumber aslinya sebelum dipakai mengambil keputusan.',
    sumber: 'proses penulisan: ' + esc(w.sumber_data || '—'),
  });

  isi.innerHTML = `<ul>${catatan.map((c) => `
    <li>${c.teks}<span class="sumber-kecil">${c.sumber}</span></li>`).join('')}</ul>`;

  tombol.addEventListener('click', () => {
    const terbuka = !isi.hidden;
    isi.hidden = terbuka;
    tombol.textContent = terbuka ? 'Buka' : 'Tutup';
    tombol.setAttribute('aria-expanded', String(!terbuka));
  });
}

/* ---- pasang semua ---- */
function pasangInteraktif(w) {
  renderGalat(w);
  pasangProgres();
  pasangKilau();
  pasangMagnetik();
  pasangTilt();
  pasangPercikan();

  // Sesudah konten baru dibuat, pasang ulang sorot & fade.
  pasangSpotlight();
  pasangFade();
}

/* ---------------------------------------------------------------- pemilih edisi
   Halaman Warta memuat edisi-edisi sebelumnya di sini. Dulu ada
   halaman Arsip terpisah, tapi fungsinya cuma menampilkan daftar edisi,
   jadi lebih masuk akal digabung ke Warta. */

async function siapkanPemilihEdisi(w) {
  const pilih = $('#pilih-edisi');
  const catatan = $('#edisi-catatan');
  if (!pilih) return;

  let daftar = [];
  try {
    const r = await fetch('arsip.json', { cache: 'no-store' });
    if (r.ok) daftar = await r.json();
  } catch (e) { /* diabaikan */ }

  // Kalau arsip.json tidak ada, minimal edisi yang sedang dibuka.
  if (!Array.isArray(daftar) || !daftar.length) {
    daftar = [{ tanggal: w.tanggal, judul: w.judul, jumlah_bagian: 0, jumlah_entri: 0 }];
  }

  daftar.sort((a, b) => String(b.tanggal).localeCompare(String(a.tanggal)));
  const aktif = String(w.tanggal || '');

  pilih.innerHTML = daftar.map((d) => {
    const ini = String(d.tanggal) === aktif;
    return `<option value="${esc(d.tanggal)}" ${ini ? 'selected' : ''}>
      ${esc(d.judul || d.tanggal)}${ini ? ' — edisi terbuka' : ''}
    </option>`;
  }).join('');

  const isiCatatan = (tgl) => {
    const d = daftar.find((x) => String(x.tanggal) === String(tgl));
    if (!d) return '';
    return `${d.jumlah_bagian || 0} bagian · ${d.jumlah_entri || 0} catatan`;
  };
  if (catatan) catatan.textContent = isiCatatan(aktif);

  pilih.addEventListener('change', () => {
    const tgl = pilih.value;
    if (catatan) catatan.textContent = isiCatatan(tgl);
    if (String(tgl) === aktif) return;
    bukaPanel(`Edisi ${tgl}`, `
      <p class="kecil redup">Untuk membuka edisi ini, jalankan perintah berikut
      lalu muat ulang halaman:</p>
      <pre class="mono kecil" style="margin-top:12px;padding:14px;background:var(--carbon);border:1px solid var(--hair);border-radius:8px;overflow-x:auto">python ronce.py web --tanggal ${esc(String(tgl))}</pre>
      <p class="samar kecil" style="margin-top:14px">Ronce belum menyimpan salinan
      lengkap semua edisi lama di web supaya tidak menumpuk berkas. Yang disimpan
      hanya ringkasannya untuk daftar ini.</p>`);
  });
}

/* ---------------------------------------------------------------- profil proyek
   Pengganti panel "Tentang data". Halaman ini menjelaskan proyeknya:
   apa ini, dari mana datanya, apa batasnya, siapa yang membuat. */

function renderProfil(w) {
  const kotak = $('#profil-isi');
  if (!kotak) return;

  const jendela = (w && w.jendela) || [];
  const bagianTerisi = Object.values((w && w.bagian) || {}).filter((v) => v.length).length;
  const totalCatatan = Object.values((w && w.bagian) || {}).reduce((a, b) => a + b.length, 0);

  kotak.innerHTML = `
    <div class="profil">

      <div class="profil-blok">
        <h3>Kenapa Ronce ada</h3>
        <p>Laporan keuangan dan pengumuman bursa ditulis untuk orang yang sudah
        terbiasa membacanya. Pembaca baru biasanya menyerah di kalimat pertama.</p>
        <p>Ronce mengambil data mentah dari Sectors, lalu menulis ulang isinya jadi
        bahasa yang bisa dipahami orang yang belum pernah membuka laporan tahunan.
        Setiap angka tetap bisa ditelusuri sampai sumbernya.</p>
        <p>Caranya sederhana: masuk dari satu pertanyaan, temukan satu cerita,
        telusuri sampai sumbernya.</p>
      </div>

      <div class="profil-blok">
        <h3>Yang Ronce lakukan</h3>
        <p>Setiap hari sistem mengambil berita, keterbukaan informasi, aksi korporasi,
        dan jadwal RUPS dari Sectors. Isinya dirangkum jadi Warta harian, lalu
        dipecah menjadi beberapa bagian supaya mudah dibaca.</p>
        <p>Ronce juga menyusun draf untuk X dan Threads. Draf itu <b>tidak pernah
        terbit sendiri</b>. Selalu menunggu persetujuan editor.</p>
      </div>

      <div class="profil-blok">
        <h3>Batas yang Ronce akui</h3>
        <p>Narasi ditulis ulang oleh model bahasa. Model bisa salah membaca angka,
        dan Ronce tidak menyembunyikan itu. Halaman Warta selalu menyertakan bagian
        "yang belum dapat dibuktikan" untuk menyebut apa yang tidak bisa dipastikan
        dari data yang tersedia.</p>
        <p>Ronce juga tidak menghubungkan pergerakan harga dengan berita kalau tidak
        ada bukti yang jelas. Kalau data kosong, Ronce mengatakannya kosong.</p>
      </div>

      <div class="profil-blok">
        <h3>Edisi yang sedang terbuka</h3>
        <dl class="profil-daftar">
          <div class="profil-baris"><dt>Edisi</dt><dd>${esc((w && w.judul) || '—')}</dd></div>
          <div class="profil-baris"><dt>Tanggal</dt><dd>${esc((w && w.tanggal) || '—')}</dd></div>
          <div class="profil-baris"><dt>Jendela data</dt><dd>${jendela.length === 2 ? `${esc(jendela[0])} sampai ${esc(jendela[1])}` : '—'}</dd></div>
          <div class="profil-baris"><dt>Isi</dt><dd>${bagianTerisi} bagian · ${totalCatatan} catatan</dd></div>
          <div class="profil-baris"><dt>Sumber</dt><dd>${esc(((w && w.sumber) || []).join(', ') || '—')}</dd></div>
          <div class="profil-baris"><dt>Status terbit</dt><dd>Menunggu persetujuan editor</dd></div>
        </dl>
      </div>

      <div class="profil-blok">
        <h3>Cara menjalankan sendiri</h3>
        <p>Ronce bisa dijalankan di komputer sendiri. Yang dibutuhkan cuma Python
        dan satu API key dari Sectors. Model AI untuk menulis ulang bisa memakai
        layanan apa pun yang kompatibel dengan OpenAI, termasuk model yang berjalan
        lokal seperti Ollama.</p>
        <a class="profil-tautan" href="https://github.com/michaelxdips/WartaPasar" target="_blank" rel="noopener">
          <svg class="ikon" aria-hidden="true"><use href="#i-kode"/></svg>
          Lihat kode di GitHub
        </a>
      </div>

    </div>`;

  // Isi footer dengan data yang sama, karena footer hanya tampil di sini.
  const ftgl = $('#footer-tanggal');
  if (ftgl) ftgl.textContent = 'Edisi ' + ((w && w.tanggal) || '—');
  const fsum = $('#footer-sumber');
  if (fsum) fsum.textContent = ((w && w.sumber) || []).join(', ') || '—';
}

/* ---------------------------------------------------------------- pencarian */

function siapkanPencarian(w) {
  const input = $('#input-cari');
  if (!input) return;
  const indeks = [];
  for (const [nama, isi] of Object.entries(w.bagian || {})) {
    for (const e of isi) {
      indeks.push({
        bagian: nama,
        emiten: e.emiten || '',
        judul: e.judul || '',
        narasi: e.narasi || '',
        teks: [e.emiten, e.judul, e.narasi, e.media].filter(Boolean).join(' ').toLowerCase(),
      });
    }
  }

  let timer;
  const jalankan = () => {
    const q = input.value.trim().toLowerCase();
    const kotak = $('#hasil-cari');
    if (!q) {
      kotak.innerHTML = '<p class="kosong">Mulai mengetik untuk mencari.</p>';
      return;
    }
    const cocok = indeks.filter((e) => e.teks.includes(q)).slice(0, 20);
    if (!cocok.length) {
      kotak.innerHTML = `<p class="kosong">Tidak ada hasil untuk “${esc(input.value)}”.</p>`;
      return;
    }
    const sorot = (t) => esc(t).replace(
      new RegExp('(' + q.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + ')', 'gi'),
      '<mark>$1</mark>');
    kotak.innerHTML = cocok.map((e, i) => `
      <article class="kartu" data-hasil="${i}" tabindex="0" role="button">
        <div class="baris-atas">
          ${e.emiten ? `<span class="kode">${sorot(e.emiten)}</span>` : ''}
          <span class="lencana netral">${esc(e.bagian)}</span>
        </div>
        ${e.judul ? `<h3>${sorot(e.judul)}</h3>` : ''}
        <p>${sorot(e.narasi.slice(0, 140))}${e.narasi.length > 140 ? '…' : ''}</p>
      </article>`).join('');

    $$('[data-hasil]', kotak).forEach((el) => {
      el.addEventListener('click', () => {
        const e = cocok[el.dataset.hasil];
        bukaPanel(e.emiten || e.bagian, `
          ${e.judul ? `<h3 style="margin-bottom:12px">${esc(e.judul)}</h3>` : ''}
          <p>${esc(e.narasi)}</p>
          <p class="samar kecil">Bagian: ${esc(e.bagian)}</p>`);
      });
    });
  };

  input.addEventListener('input', () => {
    clearTimeout(timer);
    timer = setTimeout(jalankan, 200);      // debounce 200ms
  });
}

/* ---------------------------------------------------------------- muat */

async function muat() {
  let w = null;
  try {
    const r = await fetch('warta.json', { cache: 'no-store' });
    if (r.ok) w = await r.json();
  } catch (e) { /* jatuh ke data bawaan */ }

  if (!w) w = window.WARTA_BAWAAN || null;

  if (!w) {
    $('#orbit-status').textContent = 'Data belum ada';
    $('#orbit-sapa').textContent = 'Belum ada Warta.';
    $('.orbit-ajak').textContent =
      'Jalankan "python ronce.py make" lalu muat ulang halaman ini.';
    return;
  }

  state.warta = w;
  state.indeks = bangunIndeks(w);

  // Kepala halaman
  $('#orbit-sapa').textContent = sapaan();
  $('#orbit-status').textContent = `${w.judul || 'Warta'} · data ${w.tanggal || '—'}`;
  $('#catatan-grafik').textContent = w.jendela
    ? `Jendela data ${w.jendela[0]} sampai ${w.jendela[1]}.`
    : '';

  renderStatistik(w);
  renderWarta(w);
  renderJelajah(w);
  renderEmiten(w);
  renderDisimpan(w);
  renderGalat(w);
  renderProfil(w);
  siapkanPemilihEdisi(w);
  renderKalender();
  pasangSidebar();
  siapkanOrbit(w);
  siapkanPencarian(w);

  const g = w.grafik || {};
  if (g.judul) $('#grafik-judul').textContent = g.judul;

  // Grafik digambar langsung. Ia sekarang berada di halaman Emiten yang
  // awalnya tersembunyi, dan elemen tersembunyi tidak bisa diamati
  // IntersectionObserver (tidak punya tata letak).
  gambarGrafik(g);

  // React Bits: pasang setelah semua konten ada.
  pasangSpotlight();
  pasangFade();
  pasangKilau();
  pasangMagnetik();
  pasangTilt();
  pasangPercikan();
  pasangProgres();
}

/* ---------------------------------------------------------------- ikatan */

$$('[data-halaman]').forEach((el) => {
  el.addEventListener('click', (ev) => {
    ev.preventDefault();
    pindahHalaman(el.dataset.halaman);
  });
});

$('#panel-tutup')?.addEventListener('click', tutupPanel);
$('#overlay')?.addEventListener('click', tutupPanel);
document.addEventListener('keydown', (ev) => {
  if (ev.key === 'Escape') tutupPanel();
});

const awal = location.hash.replace('#', '') || 'orbit';
pindahHalaman(HALAMAN_SAH.includes(awal) ? awal : 'orbit', { simpan: false });

muat();
