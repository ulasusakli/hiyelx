# ADR 0002: HIYELX Studio Software Stack, 14-Module Architecture, and Runtime Boundary

* **Status:** Accepted
* **Date:** 2026-11-22
* **Authors:** HIYELX Core Architecture Team
* **Target Release:** Studio V0.1 (Visual Foundation: P1–P3) → V1.0 (Robotics IDE: P4, P5, P7) → V1.5 (P6) → V2.0 (P8, P9)

---

## Context

Robotik sistem geliştiricileri; robot mimarisini tasarlamak, konfigürasyon dosyalarını yazmak, donanım sürücülerini seçmek ve telemetriyi izlemek için dağınık ve birbirinden kopuk araçlar kullanmaktadır.

HIYELX Studio'nun temel amacı, yalnızca pasif bir robot kontrol paneli veya telemetri ekranı olmak değil; robotik sistemlerin sıfırdan tasarlandığı, konfigüre edildiği, geliştirildiği, test edildiği ve canlı izlendiği merkezi bir **Robotics Development Environment (RDE)** sunmaktır.

Aynı zamanda Studio ile Runtime arasındaki mimari sınır kesinleştirilmiştir: **Studio robotu tasarlar, konfigüre eder ve izler; Runtime ise donanımı çalıştırır ve robot üzerindeki tek yetkili yürütme otoritesidir.**

---

## Decisions

### 1. Ürün Rolü ve Sınır Sözleşmesi
* **Tek Otorite İlkesi:** Studio hiçbir zaman USB, Seri, CAN veya GPIO portlarına doğrudan erişmez. Tüm donanım okuma, başlatma ve komut yönetimi Runtime üzerinden akar.
* **Bağlantı Sözleşmesi:** Studio, Runtime'a `127.0.0.1` ephemeral port üzerinde çalışan, URL fragment capability token (`X-HIYELX-Studio-Capability`) ile korunan tipli JSON HTTP API üzerinden bağlanır.
* **Local-First & Air-Gapped:** Studio ilk aşamada tamamen kullanıcının yerel iş istasyonunda çalışır; internet veya bulut bağlantısı zorunlu değildir.

### 2. Yazılım Yığını (Recommended Studio Stack)
* **Desktop Shell: Tauri 2 (Rust Backend)**
  * Studio; yerel dosya sistemine erişim, proje dizinlerini yönetme, yerel terminal açma ve hafif/güvenli masaüstü dağıtımı için Tauri 2 kullanacaktır.
  * Electron'a kıyasla çok daha düşük bellek tüketimi (RAM), yüksek performans ve gömülü güvenlik sınırları sağlar.
  * Mevcut P1/P2 statik web varlıkları (`studio/`) korunacak, masaüstü kabuğu bu varlıkları bozmadan kademeli olarak saracaktır.
* **Frontend Framework & Dil:** React + TypeScript (Strict mode).
* **Build Aracı:** Vite (hızlı HMR ve optimize edilmiş bundle üretimi).
* **Durum Yönetimi (State Management):**
  * **UI State:** Zustand (Açık paneller, aktif sekmeler, görsel tercihler).
  * **Project State:** Zustand / Proje veri modelleri (Robot topolojisi, düzenlenmiş YAML).
  * **Server / Runtime State:** TanStack Query (Runtime sağlık durumu, canlı telemetri - tek kaynak Runtime).
* **Görsel Mühendislik & Grafik Editörü:**
  * **Robot Builder / Node Canvas:** React Flow / xyflow + ELK.js (otomatik DAG yerleşimi).
  * **3D Görselleştirme:** Three.js (Robot modeli, URDF / TF ağacı - V1.5+).
* **Kod ve Konfigürasyon Editörü:** Monaco Editor (YAML, JSON, Python, C++ desteği, iki yönlü görsel/kod senkronizasyonu).
* **Tasarım Sistemi & UI Bileşenleri:** Tailwind CSS + Radix UI erişilebilir primitifler + Lucide ikonları (Karanlık tema öncelikli, endüstriyel netlikte görsel dil).
* **Veri Doğrulama:** Zod (Frontend şemaları) + Runtime OpenAPI modellerinden üretilen tipli API istemcisi.
* **Test Altyapısı:** Vitest (Birim testleri), Testing Library (Bileşen testleri), Playwright (E2E).

### 3. Sistem Mimarisi: 14 Modüllü Yapı
1. **Module 01 — Application Shell & Workspace:** Panel yöneticisi, sekmeler, global Command Palette, tema ve yerleşim kalıcılığı.
2. **Module 02 — Project & Workspace Manager:** Proje şablonları, dizin gezgini, proje meta verisi, Git entegrasyonu.
3. **Module 03 — Robot Builder & System Designer:** Node/graph tabanlı robot topoloji editörü, `robot.yaml` üretimi.
4. **Module 04 — Component & Driver Explorer:** Bileşen, sürücü ve yetenek (capability) kataloğu, uyumluluk denetimi.
5. **Module 05 — Configuration Editor:** İki yönlü görsel form + Monaco YAML editörü, fail-closed şema denetimi, diff görünümü.
6. **Module 06 — Connection & Data Flow Designer:** Konular (topics), pub/sub, komut akışları, veri haritalama.
7. **Module 07 — Application Studio:** Robotik iş akışları (workflows), görev tasarımı ve çalışma konfigürasyonu.
8. **Module 08 — Code Editor & Developer Environment:** Entegre Monaco editörü, sözdizimi vurgulama, terminal desteği.
9. **Module 09 — Runtime Manager & Device Manager:** Runtime oturum keşfi, tek oturum sahipliği, cihaz durumları.
10. **Module 10 — Robot Monitor & Visualization:** Canlı telemetri göstergeleri, motor grafikleri, 2D/3D robot izleme.
11. **Module 11 — Diagnostics & Debugging:** Log gezgini, olay zaman tüneli, hata sınıflandırıcı, correlation trace takibi.
12. **Module 12 — Simulation & Testing Studio:** Sanal robot modeli, senaryo editörü, Gazebo/MuJoCo köprüsü.
13. **Module 13 — Deployment & Release Manager:** Paketleme, wheel kurulumu, hedef makineye aktarım, rollback.
14. **Module 14 — Extensions, SDK & Marketplace:** Eklenti tarayıcısı, topluluk pazaryeri, SDK yöneticisi (V2).

### 4. Geliştirme Yol Haritası (P0 – P9 Fazları)
* **P0 — Mimari & Sözleşmeler:** Sınırlar, arayüz ilkeleri, test standartları.
* **P1 — Fixture-based Studio:** 11 durumlu statik dashboard (Commit `9998b99` ile **KABUL EDİLDİ**, korunuyor).
* **P2 — Local Runtime Host:** `127.0.0.1` ephemeral port, capability token'lı salt-okunur API (Commit `b53fbc4` ile **KABUL EDİLDİ**).
* **P3 — Live Runtime Composition:** Kurulu gerçek Runtime paketine bağlanma ve canlı DOM kompozisyonu.
* **P4 — Project & Configuration Studio:** Proje yönetimi, Robot Builder, YAML editörü.
* **P5 — Component & Driver Ecosystem:** Explorer, sürücü manifestleri, yetenek inceleyici.
* **P6 — Developer & Application Studio:** Kod editörü, iş akışı tasarımı, debugging.
* **P7 — Monitoring, Diagnostics & Visualization:** Canlı telemetri panelleri, log izleyici, hata gezgini.
* **P8 — Simulation & Testing Studio:** Sanal robot simülasyonu ve test koşucusu.
* **P9 — Deployment, Extensions & Ecosystem:** Paketleme, dağıtım ve eklenti pazaryeri.

### 5. Pre-Seed Öncelikli 5 Temel Özellik (Must Have)
1. **Robot Project Workspace:** Robot projelerinin yerel dosya sisteminde organize edilmesi.
2. **Visual Robot Builder:** Bileşenlerin ve bağımlılıkların görsel tuvalde yerleştirilmesi.
3. **Component & Driver Explorer:** Donanım ve yazılım bileşenlerinin keşfi ve yapılandırılması.
4. **Live Runtime Monitor:** Gerçek robotun anlık sağlık ve telemetri verilerinin izlenmesi.
5. **Configuration & Diagnostics:** `robot.yaml` düzenleme, doğrulama ve hata inceleme.

---

## Consequences

### Pozitif Sonuçlar
* **Geliştirici Ergonomisi:** Robotik geliştirici YAML dosyaları arasında kaybolmak yerine görsel ve kod tabanlı hibrit bir çalışma alanına kavuşur.
* **Kesin Güvenlik:** Donanım erişimi Runtime'da dondurulduğu için Studio kaynaklı port kilitlenmesi veya yarış durumları (race conditions) imkansız hale gelir.
* **Hafif ve Taşınabilir:** Tauri 2 sayesinde Electron'un devasa bellek ve paket boyutu yükünden kaçınılır.
* **Mevcut Başarıların Korunması:** Kabul edilmiş P1 ve P2 fazları ezilmeden, kademeli genişleme hattı güvenceye alınır.

### Negatif Sonuçlar ve Riskler
* **Frontend-Backend Senkronizasyon Riski:** Studio veri modeli ile Runtime Pydantic modelleri arasındaki uyumsuzluk riski, OpenAPI'den üretilen tekil TypeScript istemcisi ve sözleşme testleri (contract tests) ile kontrol edilecektir.
* **3D Görselleştirme Karmaşıklığı:** Three.js / WebGL altyapısı ilk sürümde (V0.1) zorunlu tutulmayacak; V1.5+ aşamasına kadar 2D grafik ve kart göstergeleriyle ilerlenecektir.
