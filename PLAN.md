# PLAN.md — Pengembangan fork inventor-mcp

Rencana kerja untuk memodifikasi inventor-mcp (asal: NeonGlay/inventor-mcp) agar:

1. berjalan andal di **Autodesk Inventor 2027**,
2. bisa membuat **technical drawing** (prioritas utama),
3. bisa membuat dan menganalisis **assembly**,
4. bisa membuat **exploded view**.

Pemilik proyek: Rizal. Semua pekerjaan dijalankan oleh sesi Claude Code di folder `C:\\inventor-mcp`.

\---

## Cara memakai file ini

* Baca **Aturan kerja** dan **Log progres** sebelum mulai.
* Kerjakan **satu fase per perintah**. Jangan lanjut ke fase berikutnya tanpa persetujuan Rizal.
* Di akhir fase: centang tugas yang selesai, isi Log progres, commit, push, lalu **berhenti** dan tulis laporan fase (format di bawah).
* Kalau Rizal bilang "lanjut", kerjakan fase berikutnya yang belum selesai.

## Aturan kerja

1. **Alur per fitur:** coba di `execute\_python` → kalau berhasil, pindahkan ke `src/inventor\_api.py` → `reload\_api` → daftarkan tool di `src/server.py` → tambahkan kasus ke `tests/smoke.py` → jalankan → lulus → commit.
2. **Verifikasi API dulu, jangan menebak.** Nama method dan nilai enum di rencana ini adalah petunjuk dari pengetahuan umum tentang Inventor API, belum diverifikasi di 2027. Sebelum memakainya, cek lewat probe type library (lihat `docs/inventor-api-notes.md`, bagian gencache) di proses terpisah, lalu hapus cache `gen\_py` sesudahnya.
3. **Satuan:** semua parameter tool dalam mm dan derajat. Konversi ke cm dan radian dilakukan di dalam `inventor\_api.py`.
4. **Transaksi:** operasi multi-langkah dibungkus `TransactionManager` supaya bisa di-rollback.
5. **Lokasi file uji:** semua file Inventor hasil uji disimpan di `C:\\inventor-test\\`, tidak pernah di dalam repo. Jangan menghapus atau menimpa file di luar `C:\\inventor-test\\` dan `C:\\inventor-mcp\\`.
6. **Jangan memodifikasi** `skills/` asli NeonGlay kecuali di Fase 6. Jangan menyentuh `.mcp.json`.
7. **Kalau gagal 3 kali** dengan pendekatan yang sama pada satu masalah, berhenti dan laporkan. Jangan memaksa.
8. **Catat setiap temuan API** (method yang berubah, enum yang berbeda, quirk) di `docs/inventor-2027-notes.md`. Ini sama pentingnya dengan kodenya.
9. Commit kecil dan sering, pesan commit dalam bahasa Inggris, format `fase N: ringkasan`.

## Keputusan default

Dipakai kecuali Rizal mengubahnya:

|Hal|Default|
|-|-|
|Standar gambar|Proyeksi sudut ketiga (third angle), mm, label view tanpa referensi sheet/zona (keputusan Rizal 2026-11-14). Diatur di `drawing_profiles/default.json`, lihat `docs/drawing-profiles.md`|
|Kertas|A3 landscape|
|Satuan|mm|
|Template drawing|Sementara template ISO bawaan Inventor 2027; diganti template Arjuna lewat kunci `template` di profil setelah template itu dimigrasi ke 2027|
|Title block|Diisi dari iProperties dokumen (Part Number, Description, Designer, Material)|

## Format laporan akhir fase

```
FASE N — SELESAI / SEBAGIAN / GAGAL
Tool baru: ...
Hasil smoke.py: X PASS, Y FAIL
Temuan API 2027: ...
Yang perlu Rizal cek manual di Inventor: ...
Masalah terbuka: ...
```

\---

## Fase 0 — Fondasi

Tujuan: repo siap dikembangkan dan punya jaring pengaman.

* \[x] Simpan kode `execute\_python` assembly kopling flens dari tes sebelumnya ke `experiments/assembly\_coupling.py`, dengan komentar per langkah termasuk error yang muncul dan solusinya. *(Hanya bisa kalau riwayat tes masih ada di sesi ini. Kalau tidak ada, tulis catatan di Log progres dan lewati.)*
* \[x] Ubah remote: `origin` (NeonGlay) → ganti nama jadi `upstream`; tambahkan `origin` = `https://github.com/rizaaaell/inventor-mcp.git`. Tunjukkan `git remote -v`.
* \[x] Tambahkan `.mcp.json` dan `.claude/` ke `.gitignore`.
* \[x] `pyproject.toml`: dependency menjadi `mcp\[cli]>=1.0.0,<2`.
* \[x] Buat `tests/smoke.py`: membangun silinder Ø50×10 (volume ≈ 19 635 mm³) dan flens kopling (disk Ø120×20, hub Ø60×30, bore Ø30, 4 lubang Ø11 di PCD 90), memeriksa volume dengan toleransi 0,1%, mencetak PASS/FAIL per kasus.
* \[x] Commit dan push ke `origin main`.

Selesai jika: smoke.py PASS semua, commit terlihat di GitHub fork, `.mcp.json` tidak ter-commit.

## Fase 1 — Audit Inventor 2027

Tujuan: tahu persis apa yang rusak sebelum membangun di atasnya.

* \[x] Jalankan **setiap** tool yang sudah ada minimal sekali pada part uji (termasuk hole tapped, counterbore, fillet, chamfer, circular pattern, revolve, sheet metal face/flange/cut, set/add parameter, export STEP).
* \[x] Verifikasi semua konstanta enum di bagian atas `inventor\_api.py` terhadap type library 2027.
* \[x] Perbaiki yang rusak. Setiap perbaikan dicatat di `docs/inventor-2027-notes.md` (apa yang berubah dari 2026).
* \[x] Tambahkan kasus smoke.py untuk fitur yang belum tercakup: chamfer, fillet, tapped hole, circular pattern, sheet metal flange + flat pattern.

Selesai jika: semua tool lama jalan di 2027 atau tercatat sebagai rusak beserta alasannya.

## Fase 2 — Drawing part

Tujuan: dari satu part `.ipt`, menghasilkan drawing `.idw` + PDF yang layak dirapikan manusia.

Tool yang dibuat:

|Tool|Fungsi|Petunjuk API (verifikasi dulu)|
|-|-|-|
|`create\_drawing(template, sheet\_size)`|Drawing baru|`Documents.Add(kDrawingDocumentObject, template)`; enum dokumen drawing kemungkinan 12292|
|`add\_base\_view(model\_path, x, y, scale, orientation, style)`|View utama|`Sheet.DrawingViews.AddBaseView(...)`|
|`add\_projected\_view(parent, x, y)`|Proyeksi ortografis|`AddProjectedView(...)`|
|`add\_section\_view(parent, x1, y1, x2, y2, label, x, y)`|Potongan|Butuh sketch garis potong di parent view, lalu `AddSectionView(...)`|
|`add\_detail\_view(parent, cx, cy, radius, scale, label, x, y)`|Perbesaran|`AddDetailView(...)`|
|`retrieve\_dimensions(view)`|Ambil dimensi model|`GeneralDimensions.GetRetrievableDimensions(view)` lalu `Retrieve`|
|`add\_centerlines(view)`|Garis sumbu otomatis|`DrawingView.SetAutomatedCenterlineSettings`|
|`add\_dimension(view, ...)`|Dimensi manual linear/diameter/radius|Lewat `DrawingCurve` dan `CreateGeometryIntent`|
|`set\_title\_block(fields)`|Isi title block|iProperties `Design Tracking Properties` dan `Summary Information`|
|`list\_views()`|Daftar view: nama, posisi, skala, ukuran bounding box||
|`export\_sheet\_png(path, width)`|Gambar sheet untuk diperiksa visual|`ActiveView.SaveAsBitmap` atau padanannya|
|`export\_pdf(path)`|Hasil akhir|Translator PDF bawaan Inventor|

Aturan khusus fase ini:

* Setelah setiap perubahan tata letak, panggil `export\_sheet\_png`, **buka gambarnya dengan Read**, dan periksa sendiri: view keluar kertas, dimensi bertumpuk, teks terpotong, view saling tumpang tindih.
* `add\_base\_view` dan kawan-kawan harus menolak posisi yang membuat view keluar batas sheet.

Uji penerimaan: buat drawing flens kopling A3 dengan front view, top view, section A-A melalui dua lubang baut, retrieve dimensions, centerlines, title block terisi, ekspor PDF.

Selesai jika: PDF terbuka, semua view di dalam kertas, tidak ada view yang tumpang tindih, dan Rizal mengonfirmasi tampilannya.

## Fase 3 — Assembly

Tujuan: assembly dibangun lewat tool, bukan kode mentah.

|Tool|Fungsi|Petunjuk API (verifikasi dulu)|
|-|-|-|
|`create\_assembly(template)`|Assembly baru|enum dokumen assembly kemungkinan 12291|
|`place\_component(path, x, y, z, grounded)`|Menaruh komponen|`Occurrences.Add(path, matrix)`|
|`list\_occurrences()`|Daftar komponen + status grounded||
|`add\_constraint(type, occ1, geom1, occ2, geom2, offset)`|mate, flush, insert, angle, tangent|`Constraints.AddMateConstraint` dst.|
|`find\_occurrence\_face/edge/axis(occ, x, y, z)`|Cari geometri komponen berdasarkan koordinat|Pakai proxy geometri (`CreateGeometryProxy`)|
|`get\_dof(occ)`|Derajat kebebasan tersisa||
|`get\_bom(view)`|BOM structured / parts only|`ComponentDefinition.BOM`|
|`analyze\_interference()`|Interferensi antar komponen + volume|`AnalyzeInterference`|
|`pattern\_component(occ, ...)`|Pola komponen (mis. baut ×4)||

* \[x] Ambil logika dari `experiments/assembly\_coupling.py` sebagai dasar.
* \[x] Simpan urutan constraint yang dibuat ke file log di samping `.iam` (untuk draf diagram alur perakitan nanti).

Uji penerimaan: bangun ulang kopling flens hanya dengan tool fase ini, tanpa `execute\_python`. BOM benar (2 flens, 2 poros, 4 baut, 4 mur, 8 ring), DOF semua komponen 0, interferensi hanya baut-mur di lubang tap (artefak pemodelan ulir, harus dilaporkan sebagai artefak).

## Fase 4 — Drawing assembly

* \[x] `add\_parts\_list(view, x, y)` — `Sheet.PartsLists.Add`.
* \[x] `add\_balloons(view)` — balloon otomatis per komponen, posisi tidak bertumpuk.
* \[x] `add\_base\_view` mendukung assembly dan representasi (view rep).

Uji penerimaan: drawing assembly kopling A3 dengan front view, section melalui sumbu, parts list, balloon untuk setiap komponen, PDF.

## Fase 5 — Exploded view

* \[x] **Probe dulu:** apakah API Presentation (`.ipn`) di 2027 bisa membuat dokumen presentasi, menambah storyboard/snapshot, dan membuat tweak komponen? Catat hasilnya di `docs/inventor-2027-notes.md`.
* \[-] (Tidak bisa, lihat log) Kalau bisa: tool `create\_presentation`, `add\_tweak(occ, direction, distance)`, `auto\_explode(axis, spacing)`, dan `add\_base\_view` dari `.ipn`.
* \[x] Kalau tidak bisa: tool `create\_exploded\_copy(assembly, axis, spacing)` yang menyalin assembly dan menggeser komponen dengan transformasi (tanpa constraint), lalu view drawing diambil dari salinan itu. Jelaskan keterbatasannya di laporan.

Uji penerimaan: drawing exploded view kopling flens dengan balloon dan parts list.

## Fase 6 — Skill

* \[x] `skills/inventor-drawing/SKILL.md`: kapan memakai tiap tool drawing, aturan pemilihan view (view paling informatif sebagai front, jumlah view minimum), strategi dimensi (retrieve dulu, manual hanya untuk yang kurang), kapan section/detail, standar ISO first angle, loop verifikasi lewat `export\_sheet\_png`, jebakan API yang ditemukan di Fase 2 dan 4.
* \[x] `skills/inventor-assembly/SKILL.md`: urutan constraint yang andal, grounded component pertama, mencari geometri lewat koordinat, membaca hasil interferensi (termasuk artefak ulir), jebakan dari Fase 3 dan 5.
* \[x] Perbarui `skills/inventor-modeling/SKILL.md` untuk perbedaan 2027 dari `docs/inventor-2027-notes.md`.
* \[x] Perbarui `README.md`: daftar tool lengkap, versi yang diuji (2027.x), cara install termasuk catatan `mcp<2`.

Selesai jika: sesi Claude Code **baru** yang hanya membaca skill bisa membuat drawing part dan assembly sederhana tanpa membaca PLAN.md.

\---

## Log progres

Diisi oleh sesi Claude Code setiap akhir fase. Entri terbaru di bawah.

|Tanggal|Fase|Status|Catatan|
|-|-|-|-|
|2026-11-13|0|Selesai|smoke.py 2/2 PASS (silinder 19 635,0 mm³; flens 267 697,2 mm³). Commit a096a41 di origin/main; `.mcp.json` dan `.claude/` diabaikan git. Run pertama smoke.py menggantung: tidak ada Inventor yang berjalan, `connect()` menyalakan instance baru yang tidak merespons. Lulus setelah Inventor dibuka manual.|
|2026-11-14|1|Selesai|tests/audit_tools.py: 57 PASS, 0 FAIL (semua 36 tool). smoke.py 6/6 PASS. Diperbaiki: export_document (nama translator berubah di 2027, sekarang lewat ClassId), dialog Style Conflict yang menahan create_part (SilentOperation), list_edges/find_edge untuk lingkaran penuh, tabel SurfaceTypeEnum, stderr execute_python. Enum lain cocok dengan RxInventor.tlb 2027. Detail di docs/inventor-2027-notes.md.|
|2026-11-14|2|Menunggu konfirmasi|12 tool drawing baru. Uji penerimaan: experiments/drawing_flange.py membuat Flens_A3.idw + PDF A3 1 halaman (front, top, section A-A lewat dua lubang baut, 8 dimensi hasil retrieve, centerline, title block terisi); list_views tanpa masalah tata letak, diperiksa juga lewat PNG. Audit 77 PASS, smoke 7/7 PASS. Template drawing: ISO.idw bawaan Inventor 2027, karena template tim perlu dimigrasi. Tunggu Rizal mengonfirmasi tampilan PDF.|
|2026-11-14|2|Menunggu konfirmasi|Revisi atas masukan Rizal: profil drawing (`drawing_profiles/default.json`) dengan sudut ketiga, mm, tanpa nol di belakang, label tanpa '/ .A6'; tool baru add_hole_note ('4x Ø11 THRU'), list_dimensions, delete_dimension, add_dimension kind 'pcd'. Drawing flens dibangun ulang: PCD Ø90, hole note, dimensi ganda dibuang, list_views tanpa masalah. Audit 81 PASS, smoke 7/7. Folder `references/` (diabaikan git) disiapkan untuk standar, gamtek baseline, dan template Arjuna.|
|2026-11-14|2|Menunggu konfirmasi|Revisi kedua: profil default memakai template Arjuna A3 (salinan hasil migrasi di references/templates/2027/), satu desimal koma tanpa nol di belakang seperti baseline 2024; profil `iso` untuk mesin tanpa file tim. set_title_block membaca field dari title block mana pun (prompt, iProperty drawing/model, MATERIAL lewat material part). add_centerlines kini menarik setiap sumbu silinder sepanjang fiturnya + 3 mm. View isometrik di drawing flens. Audit 82 PASS, smoke 7/7. Style Arjuna Fix.styxml belum terimpor (API tidak menyediakan impor).|
|2026-11-14|2|Menunggu konfirmasi|Revisi ketiga: style Arjuna Fix.styxml + center mark diimpor ke template A3 (lewat Style Editor, API tidak punya impor) dan jadi default; DOCUMENT TYPE ditambahkan ke title block; default ENGINEERING DRAWING / APPROVED BY nama approver tim lewat profil; tool baru set_tolerance, move_dimension, add_gdt, add_datum, add_surface_finish. Drawing flens: Ø30 H7, datum A/B, flatness, perpendicularity, position, Ra. Proyeksi sudah sudut ketiga (diverifikasi). 56 tool, audit 85 PASS, smoke 7/7. Template A4/A2/portrait belum diimpor style-nya.|
|2026-11-14|2|Menunggu konfirmasi|Revisi keempat: style Arjuna kini benar-benar dipakai (Arjuna Standard / Object Defaults / Leader / Note Text, karena style library menimpa style bernama sama); toleransi umum .X ±0,2 .XX ±0,1 .XXX ±0,05 dari profil; tata letak flens mengikuti baseline: diameter sebagai dimensi Ø linear di luar section, front view hanya PCD + hole note + frame position, datum B dan Ra 1,6 di garis ekstensi Ø30 H7. add_dimension prefix, leader ke titik bebas, FCF tanpa leader; list_views juga melaporkan teks di luar border. Audit 85 PASS, smoke 7/7.|
|2026-11-14|2|Menunggu konfirmasi|Revisi kelima: top view dengan garis tersembunyi (lubang dan bore); lokasi lubang lewat PCD Ø90 basic dan sudut 90° basic, dirujuk oleh position Ø0,2 A B; add_dimension kind 'angle'. Audit 86 PASS, smoke 7/7.|
|2026-11-14|2|Menunggu konfirmasi|Revisi keenam: garis sumbu dan lingkaran PCD jadi titik-strip (layer centerline ISO menggambar lingkaran sebagai strip biasa yang mirip hidden line); PCD masuk ke hole note '4x Ø11 THRU / EQ SP ON PCD Ø90' dengan frame position di bawahnya; chamfer jadi catatan '2x 1 X 45°' (tool add_chamfer_note). Audit 87 PASS, smoke 7/7.|
|2026-11-14|2|Menunggu konfirmasi|Revisi ketujuh: center mark setiap lubang dan lingkaran utama diperpanjang melewati tepi lingkaran (center mark pola otomatis yang terkunci diganti center mark biasa); top view mendapat sumbu lubang tersembunyi. Audit 87 PASS, smoke 7/7.|
|2026-11-14|2|Selesai|Rizal mengonfirmasi tampilan Flens_A3.pdf. Fase 2 ditutup dengan 21 tool drawing (57 total), profil drawing Arjuna, template Arjuna A3 hasil migrasi dengan style Arjuna Fix, audit 87 PASS, smoke 7/7. Sisa: style .styxml belum diimpor ke template A4/A2/portrait; teks Ra 1,6 sedikit menimpa arsiran.|
|2026-11-14|3|Menunggu konfirmasi|9 tool assembly baru (66 total): create_assembly, place_component, list_occurrences, list_occurrence_geometry, add_constraint (mate/flush/insert/angle/tangent), get_dof, get_bom, analyze_interference, pattern_component. Pencarian geometri lewat selector di koordinat part (plane:/axis:/circle:/face:/cylinder:/edge:), bukan tool find_occurrence_* terpisah. Uji penerimaan experiments/assembly_coupling_tools.py: Kopling_Flens_tools.iam, 20 komponen, 38 constraint, BOM 2/2/4/4/8, DOF semua 0, interferensi hanya 4 pasang baut-mur 187,51 mm³ ditandai artefak ulir; urutan constraint di Kopling_Flens_tools.constraints.json. Audit 101 PASS, smoke 8/8.|
|2026-11-14|3|Menunggu konfirmasi|Revisi atas masukan Rizal: pengencang kopling diambil dari Content Center (DIN 933 M10x60, DIN 934 M10, DIN 125-1 A 10,5; file dibuat di folder Content Center project aktif atas persetujuan Rizal), satu set baut di lubang +X lalu pattern_component 4x mengelilingi sumbu flens. Tool baru list_content_center dan place_content_center (68 total). Artefak ulir kini hanya untuk pasangan lubang tap vs part ber-ulir; lubang tap tanpa pasangan ber-ulir ditandai 'likely'. Hasil: BOM 2/2/4/4/8, DOF semua 0, interferensi hanya 4 baut-mur 176,85 mm³ (artefak ulir). Audit 103 PASS, smoke 8/8.|
|2026-11-14|3|Selesai|Rizal mengonfirmasi hasil kopling. Fase 3 ditutup dengan 11 tool assembly (68 total): assembly, selector geometri, constraint dengan log urutan, DOF, BOM, interferensi dengan deteksi artefak ulir, pattern, dan Content Center. Audit 103 PASS, smoke 8/8. Sisa: nama constraint panjang untuk part Content Center; sketch Flens.ipt masih tampil di assembly.|
|2026-11-14|4|Menunggu konfirmasi|Tool baru add_parts_list dan add_balloons; add_base_view menerima design_view/positional; add_section_view menerima no_hatch (poros tanpa arsir, karena API tidak punya section participation per komponen). 70 tool. Uji penerimaan experiments/drawing_coupling.py: Kopling_Flens_A3.idw + PDF, front view, section A-A lewat sumbu dan dua baut, iso, parts list di atas title block gaya Arjuna, 5 balloon tanpa leader bersilangan, list_views tanpa masalah. Ditemukan dan diperbaiki: menutup part yang masih dipakai assembly memunculkan dialog 'improper argument' lalu crash; pembersihan di audit, smoke, dan eksperimen kini lewat close_documents_in. Audit 104 PASS, smoke 8/8 dua kali berturut-turut.|
|2026-11-14|4|Selesai|Rizal mengonfirmasi Kopling_Flens_A3.pdf. Fase 4 ditutup dengan add_parts_list, add_balloons, design_view/positional di add_base_view, dan no_hatch di add_section_view (70 tool). Penutupan dokumen tes lewat close_documents_in mencegah dialog 'improper argument' dan crash. Audit 104 PASS, smoke 8/8. Sisa: DESCRIPTION Flens/Poros kosong (belum ada tool iProperty part).|
|2026-11-14|5|Menunggu konfirmasi|Probe API presentasi: .ipn bisa dibuat dan diisi assembly (InsertModel), tetapi tweak dan snapshot view tidak bisa ditambah lewat API 2027 (Publications(Context) selalu E_INVALIDARG). Jalur cadangan: create_exploded_copy (salinan .iam tanpa constraint/pattern), explode_components (geser komponen, dicatat di .explode.json), add_explode_trails (garis titik-strip), add_base_view spin (iso diputar supaya baut tidak berimpit). 73 tool. Uji penerimaan experiments/drawing_coupling_exploded.py: Kopling_Flens_exploded_A3.idw + PDF, iso exploded 1:2, 5 trail, parts list, 5 balloon, list_views tanpa masalah. Keterbatasan: exploded copy tidak ikut berubah kalau assembly asli berubah (harus dibuat ulang), tanpa animasi/storyboard. Audit 105 PASS, smoke 8/8 dua kali.|
|2026-11-14|5|Selesai|Rizal mengonfirmasi Kopling_Flens_exploded_A3.pdf. Fase 5 ditutup dengan jalur salinan exploded (create_exploded_copy, explode_components, add_explode_trails, spin di add_base_view; 73 tool), karena API 2027 tidak bisa menambah tweak atau snapshot di .ipn. Audit 105 PASS, smoke 8/8. Sisa: belum ada auto_explode; salinan harus dibuat ulang jika assembly asli berubah.|
|2026-11-15|6|Menunggu konfirmasi|Skill baru inventor-drawing dan inventor-assembly; inventor-modeling diperbarui untuk 2027 (tabel surface type, perbedaan 2027, probe typelib tanpa gen_py, reload_api); README ditulis ulang (73 tool, diuji di Inventor 2027.1, Python 3.13, mcp 1.30 dipin <2, empat skill, profil, tes); llms-install.md disamakan. Skill mengikuti profil Arjuna sudut ketiga, bukan ISO sudut pertama seperti tulisan awal rencana. Uji penerimaan: agen baru yang hanya membaca skill membuat Housing.ipt + drawing A3 (section, H7, hole note, title block), assembly dengan baut/ring/mur Content Center dan pattern (DOF 0, BOM benar, hanya artefak ulir) dan drawing assembly dengan parts list + 4 balloon, tanpa execute_python; list_views bersih. Celah yang ditemukan agen dimasukkan ke skill: hitungan '2x' di hole note butuh lubang berpola (diverifikasi), label section di atas view, dimensi antar-pusat lubang lewat titik di lingkaran, view tidak bisa dipindah, PART NUMBER Arjuna hanya prompt di sheet.|
|2026-11-15|6|Menunggu konfirmasi|Revisi atas masukan Rizal: teks DOCUMENT TYPE di title block ditengahkan (kelima template); MATERIAL jadi prompt dan selalu diisi otomatis (material part; untuk assembly satu material atau 'VARIOUS, SEE PART DRAWINGS'; 'NONE' kalau Generic; bisa diganti lewat profil); drawing assembly default jadi exploded (skill drawing dan assembly diubah). Tool baru (79 total): auto_explode (dari log constraint, arah dari normal muka dudukan), move_view, delete_view, list_notes, delete_note, set_properties (Part Number/Description), count di add_hole_note. Drawing exploded kopling memakai auto_explode dan parts list kini berisi KF-001 Coupling flange / KF-002 Shaft Ø30. Audit 111 PASS, smoke 8/8 dua kali.|
|2026-11-15|6|Menunggu konfirmasi|Revisi kedua: semua isian title block rata tengah horizontal dan vertikal di selnya (center_fields, kelima template); aturan baru: assembly yang dilas digambar rakitan, yang tidak dilas exploded saja. Skill dan tool las baru (82 tool): create_weldment, add_cosmetic_weld, add_weld_symbol (ISO 2553: fillet, butt, plug, spot, sisi arrow/other/both, all-around, field, tail), view weldment otomatis di state welds. API 2027 tidak bisa membuat weld bead. Diperbaiki: nama constraint kembar, komponen 'Welds' tanpa file di weldment, kurva las yang menolak dibaca. Uji penerimaan experiments/weldment_bracket.py: braket L, DOF 0, cosmetic weld dua sisi, drawing dengan simbol a4 dua sisi + 135, parts list, balloon, MATERIAL Steel. Audit 115 PASS, smoke 8/8 dua kali.|
|2026-11-15|6|Selesai|Rizal mengonfirmasi hasil Fase 6. Skill inventor-modeling (2027), inventor-assembly, inventor-drawing, inventor-weld dan inventor-din-parts; README untuk 82 tool. Title block Arjuna dengan isian rata tengah dan MATERIAL selalu terisi; drawing assembly exploded (auto_explode), weldment digambar rakitan dengan simbol las ISO 2553. Uji skill-only oleh sesi baru lolos. Audit 115 PASS, smoke 8/8. Sisa: weld bead solid tidak tersedia di API 2027; style Arjuna belum diimpor ke template A4/A2/portrait; auto_explode hanya untuk tumpukan satu sumbu.|
|2026-11-15|-|Selesai|Style Arjuna (Arjuna Fix, Mini Center Mark, Super Mini Center Mark) diimpor ke template A4, A2, portrait A3 dan portrait A4 lewat Style Editor (API tidak punya impor); kelima template kini memakai Arjuna Standard. Diperbaiki: di template portrait isian DOCUMENT TYPE jatuh ke baris UNIT/SCALE/DATE, kini ditaruh di sel labelnya. Diverifikasi dengan drawing flens dari tiap template: Arjuna Standard, dimensi Ø120, list_views bersih.|
|2026-11-15|-|Selesai|Pemakaian nyata: gamtek wheel hub AISI 4140 (3 part + assembly las) ke Gamtek\Claude di project. Ditemukan dan dibetulkan di assembly atas izin Rizal: flange bertumpang tindih 1569 mm³ dan bebas aksial, kini flush ujung shaft. Perbaikan tool: presisi dimensi otomatis (121,42 tidak lagi 121,4), thread note pada ulir luar, lingkaran PCD untuk lubang sketch, set_component_visibility dan add_parts_list hide (shaft varian), balloon menunjuk ujung tepi melintang, simbol las ikut dicek layout. 83 tool, audit 117 PASS, smoke 8/8.|
|2026-11-16|-|Selesai|Konvensi penempatan dari revisi WH-003 Rizal: lubang pada PCD jadi satu catatan diameter dua baris "4x Ø8 THRU / ON PCD 76, EQ SP" tanpa dimensi PCD terpisah (add_dimension suffix); FCF position tepat di bawah catatan itu (add_gdt dimension=); datum sumbu di shoulder dimensi Ø (add_datum dimension=); sudut lubang dari sumbu horizontal (add_dimension angle tanpa x2/y2, Inventor menolak titik 180° jadi diukur dari sisi kanan); view biasa part berlubang memakai hidden line. Skill inventor-drawing diperbarui, WH-002 dibuat ulang. Audit 119 PASS, smoke 8/8.|
|2026-11-16|-|Selesai|MMC/LMC di add_gdt (modifier="mmc"/"lmc" setelah nilai, "B(M)" untuk datum; simbol Unicode Ⓜ/Ⓛ dirender Inventor sebagai simbol ISO). Sheet metal di drawing: add_base_view(flat_pattern=True) dan tool baru add_bend_notes (84 tool) yang memberi "UP/DOWN 90° R2" di setiap garis tekuk; catatan tekuk ikut dicek layout. Datum identifier native tidak ada di API drawing 2027, add_datum meniru bentuknya. Audit 120 PASS, smoke 8/8. Catatan: layar terkunci membuat Inventor hilang dari ROT, sehingga proses baru tidak bisa tersambung dan connect() membuka Inventor kedua; perlu tutup semua Inventor dan server MCP lama lalu buka ulang.|
|2026-11-16|-|Selesai|Gamtek pertama di luar wheel hub: RK-002 Rear Knuckle (v1_MIR_MIR1, Aluminium 7075) di Rear Wheel Assembly\Gamtek\Claude, A2 1:1 dengan section bore, 2x Ø75 N7 untuk 32009 X, datum A muka/B sumbu bore, position lubang caliper Ø0,2Ⓜ; sisi mirror (RK-001) ditunda atas permintaan Rizal. Perbaikan tool: dimensi linear ke lingkaran selalu dari pusatnya (sebelumnya 50,04 untuk 50), dan material dicari di semua library ketika Inventor tidak punya library aktif (set_title_block gagal setelah Inventor dibuka ulang). Audit 120 PASS, smoke 8/8.|
