# HIYELX Studio P3 — Live Runtime Composition Technical Design & Codex Task Plan

* **Document Reference:** `HIYELX-DESIGN-STUDIO-P3`
* **Status:** Proposed Technical Design (Ready for Bounded Codex Execution)
* **Date:** 2026-11-24
* **Package Baseline:** `hiyelx==0.2.0a1`
* **Normative Parents:**
  * [`ADR 0002 v1.1`](../decisions/0002-studio-software-stack-and-architecture.md)
  * [`Studio Engineering Specification v1.1`](studio-engineering-specification.md)
  * [`Studio Local Host Contract (P2)`](studio-local-host.md)

---

## 1. Amaç ve Sınırlar

P3 fazı, P1'de kabul edilen statik fikstür arayüzü (`9998b99`) ve P2'de kabul edilen güvenli yerel host / transport / launcher altyapısı (`b53fbc4`) arasında **gerçek, canlı ve fikstürle asla karışmayan Runtime kompozisyonunu** kurar ve bunu kurulu (non-editable) wheel ortamında doğrular.

### 1.1. Mevcut P2 Kod Tabanı Gerçeği (Doğrulanmış Baseline)
P3 görevleri mevcut kodu yeniden yazmamalı; yalnızca eksik canlı kompozisyon ve doğrulama katmanını eklemelidir:

| Mevcut Bileşen (Main'de Hazır) | Dosya | Durum |
|---|---|---|
| P1 statik 11-durumlu fikstür kabuğu | `studio/index.html`, `studio/studio.css`, `studio/fixtures.js`, `studio/app.js` | **Dondurulmuş** (`tests/studio/test_p1_preservation.py` SHA-256 korumalı) |
| P2 DOM-bağımsız tarayıcı transport kontrolcüsü | `studio/host-client.js` | **Hazır** (`HiyelxStudioHostClient.createController`, single-flight 1 Hz polling, `#capability=` tüketimi) |
| P2 salt-okunur Studio uygulama adaptörü | `src/hiyelx/studio/application.py` | **Hazır** (`list_sessions`, `get_preview`, `StudioErrorCode`) |
| P2 yerel IPv4 loopback HTTP host'u | `src/hiyelx/studio/host.py` | **Hazır** (`127.0.0.1:0`, `421` Host, `403` Origin/Capability, `405` No-CORS, `/api/v1/meta`, `/sessions`, `/preview`) |
| P2 kurulu varlık staged launcher & CLI | `src/hiyelx/studio/launcher.py`, `src/hiyelx/cli.py` (`hiyelx studio`) | **Hazır** (`hiyelx/studio/assets/*` wheel force-include, `0o700`/`0o600` staging) |
| **P3 Eksik Katman** | **Canlı DOM kompozisyonu + Runtime bilgi keşfi + kurulu wheel canlı doğrulaması** | **P3 Kapsamı** (Şu an `hiyelx studio` yalnızca statik `index.html`'i açıyor; `host-client.js` DOM'a bağlı değil) |

### 1.2. Kapsam Dışı (P3'te Kesinlikle Yapılmayacaklar)
* Runtime başlatma, durdurma, motor/zaman komutu gönderme veya oturum temizleme (`POST`/`PUT`/`DELETE` yasaktır; P3 tamamen salt-okunurdur).
* P1 statik dosyalarının (`index.html`, `studio.css`, `fixtures.js`, `app.js`) tek bir byte'ının bile değiştirilmesi.
* Tauri 2 masaüstü kabuğu, React/Vite geçişi, proje düzenleme veya SSE akışı (bunlar P4 ve P7 kapsamındadır).
* Fiziksel donanım erişimi, harici ağ dinlemesi (`0.0.0.0`, `::1`), bulut servisi veya kalıcı tarayıcı depolaması (`localStorage`, cookie).

---

## 2. P1/P2 Korumalı Canlı Kompozisyon Mimarisi (Zero-Mixing)

`tests/studio/test_p1_preservation.py` şu iki değişmezi zorunlu kılar:
1. `studio/index.html`, `studio/studio.css`, `studio/fixtures.js` ve `studio/app.js` byte-byte P1 SHA-256 özetlerine eşit kalmalıdır.
2. Bu dört dosya içinde `host-client.js` referansı bulunmamalıdır.

Bu değişmezleri zayıflatmadan canlı kompozisyonu sağlamak için **ayrı giriş noktası (entry-route separation)** kullanılır:

```text
GET /                  -> studio/index.html      (Dondurulmuş P1 fikstür prototipi — host-client.js YOK)
GET /studio.css        -> studio/studio.css      (Paylaşılan salt-okunur stil — byte-identical)
GET /fixtures.js       -> studio/fixtures.js     (Yalnızca P1 statik prototip için)
GET /app.js            -> studio/app.js          (Yalnızca P1 statik prototip için)
GET /host-client.js    -> studio/host-client.js  (P2 DOM-bağımsız transport kontrolcüsü)
GET /live              -> studio/live.html       (YENİ P3 canlı giriş belgesi — fixtures.js YOK)
GET /live-app.js       -> studio/live-app.js     (YENİ P3 canlı DOM adaptörü — host-client.js'yi DOM'a bağlar)
```

### 2.1. Yapısal Fikstür–Canlı İzolasyonu
* `studio/live.html` **asla** `fixtures.js` veya `app.js` yüklemez; yalnızca `studio.css`, `host-client.js` ve `live-app.js` yükler.
* `StudioHost.launch_url`, canlı başlatma için `http://127.0.0.1:<port>/live#capability=<token>` üretir.
* Böylece fikstür verisi canlı oturumda bellek düzleminde dahi mevcut değildir; "fikstür verisinin canlı veri gibi görünmesi" yapısal olarak imkânsız hale gelir.
* P1 doğrulaması için `GET /` erişilebilir kalır ve P1'in tüm kabul testleri değişiklik olmadan geçmeye devam eder.

---

## 3. Runtime Keşfi, Paket İzolasyonu ve Süreç Yaşam Döngüsü

### 3.1. Bağımsız Süreç Modeli
```text
Terminal 1 (Runtime Owner)                 Terminal 2 (Studio Host)
──────────────────────────                 ────────────────────────
hiyelx runtime start sim-motor.yaml        hiyelx studio
  └─> LocalControlServer (Unix socket)       ├─> Asset staging (0o700 / 0o600)
  └─> RuntimeOperations (in-process)         ├─> StudioHost (127.0.0.1:<ephemeral>)
                                             ├─> Browser open (/live#capability=...)
                                             └─> Read-only adapter -> Unix socket
```
* **Süreç Bağımsızlığı:** `hiyelx studio` kapatıldığında veya tarayıcı sekmesi kapandığında çalışan Runtime oturumu kesinlikle durdurulmaz, sıfırlanmaz veya dosyaları değiştirilmez.
* **Kurulu Paket (Installed-Wheel) Keşfi:**
  * `launcher.py`, varlıkları yalnızca kurulu paketten (`importlib.resources.files("hiyelx.studio").joinpath("assets")`) okur; kaynak dizinine geri düşmez.
  * `pyproject.toml` `[tool.hatch.build.targets.wheel.force-include]` tablosuna `studio/live.html` ve `studio/live-app.js` eklenir; `STUDIO_ASSET_NAMES` tam 7 dosyayı katı biçimde doğrular (`index.html`, `studio.css`, `fixtures.js`, `app.js`, `host-client.js`, `live.html`, `live-app.js`).
  * P3 kabul testinde, kaynak ağacı dışındaki temiz bir sanal ortamda kurulmuş `.whl` içinden `hiyelx` ve `hiyelx.studio` içe aktarım yolunun `site-packages` olduğu kanıtlanır.
* **Salt-Okunur Runtime Keşfi:**
  * Oturum keşfi mevcut `hiyelx.studio.application.list_sessions` → `list_observable_sessions` sınırını kullanır (symlink reddi, maks 128 girdi / 64 oturum, sıfır artefakt mutasyonu, kilit probu anında serbest).
  * Kurulu Runtime yetenek/model özeti için yeni salt-okunur adaptör fonksiyonu `get_runtime_info()` tanımlanır: `hiyelx.__version__`, desteklenen konfigürasyon şemaları (`("1", "2")`), kayıtlı yerleşik bileşen modelleri (yalnızca açık kayıt defterinden okunan ad, `ComponentCategory` ve `ComponentCapability` listesi — dinamik modül import veya donanım taraması yapılmaz).

---

## 4. Runtime Host ve Tipli API Sözleşmeleri

### 4.1. Korunan P2 Rotaları (Sıfır Kırıcı Değişiklik)
* `GET/HEAD /api/v1/meta` → `{"app_version":"0.2.0a1","host_version":"1","ready":true,"schema_version":"1"}`
* `GET/HEAD /api/v1/sessions` → `{"schema_version":"1","sessions":[...]}`
* `GET/HEAD /api/v1/sessions/{session}/preview` → kanonik schema-v1 `SimulationPreviewSnapshot` JSON

### 4.2. Yeni P3 Salt-Okunur Keşif Rotası: `GET/HEAD /api/v1/runtime/info`
* **Güvenlik:** P2 API rotalarıyla aynı kurallar zorunludur (`Host` → `421`, `Origin` → `403`, `X-HIYELX-Studio-Capability` → `403`, yalnızca `GET`/`HEAD` → diğerleri `405`, tüm güvenlik başlıkları, `<= 32,768` byte, `4.0 s` handler zaman aşımı).
* **Başarı Şeması (Tam Anahtar Kümesi, Sıralı, Kompakt UTF-8 JSON):**
  ```json
  {
    "package_version": "0.2.0a1",
    "registered_models": [
      {
        "capabilities": ["can_set_velocity", "has_angular_position", "has_angular_velocity"],
        "category": "actuator",
        "model": "mock.motor"
      }
    ],
    "schema_version": "1",
    "supported_config_schemas": ["1", "2"]
  }
  ```
* **Gizlilik ve Temizlik Sınırı:** Yanıtta dosya sistemi yolu, kullanıcı adı, PID, çalışma dizini, ortam değişkeni veya donanım port bilgisi kesinlikle yer alamaz.
* **Hata Sözleşmesi:** Mevcut 11 sabit hata üçlüsü (`studio-local-host.md` §4.3) aynen korunur; dahili istisnalar `500 application_error` olarak sanitize edilir.

---

## 5. Canlı DOM Durum Makinesi ve Hata / Degraded Durumları

`studio/live-app.js`, `HiyelxStudioHostClient.createController(...)` tarafından yayınlanan durum nesnelerini aşağıdaki deterministik tabloya göre DOM'a yansıtır (yalnızca `textContent` / `createElement`, sıfır `innerHTML`):

| Controller Durumu / Hata Kodu | Üst Rozet (`connection-badge`) | Severity | Oturum Seçici | Kaynak Izgarası (`resource-grid`) | Kullanıcı Mesajı |
|---|---|---|---|---|---|
| `initializing` / `connecting` | `Connecting` | `neutral` | Pasif / yükleniyor | Boş durum paneli | Yerel Runtime Host'a bağlanılıyor. |
| `no_sessions` (oturum listesi boş) | `No active session` | `neutral` | Boş + `Refresh` | Boş durum paneli | Çalışan yerel Runtime oturumu bulunamadı (`hiyelx runtime start ...`). |
| `fresh` (geçerli anlık görüntü) | `Live · Connected` | `ok` | Aktif + `Refresh` | Sıralı kaynak kartları + canlı metrikler | Canlı simülasyon oturumu okunuyor (salt-okunur). |
| `stale` (1–2 geçici yenileme hatası) | `Stale snapshot` | `warning` | Aktif + `Refresh` | Son geçerli görüntü korunur + yaş göstergesi | Son yenileme başarısız oldu; son doğrulanmış anlık görüntü gösteriliyor. |
| `paused` (sekme gizli veya manuel duraklatma) | `Paused` | `neutral` | Aktif | Son geçerli görüntü + duraklatıldı etiketi | Sekme arka planda / izleme duraklatıldı; odaklanınca yenilenir. |
| `session_not_running` (`404`) | `Session stopped` | `warning` | Yenilenebilir | Temizlenir (eski oturum verisi taşınmaz) | Seçili Runtime oturumu artık çalışmıyor. |
| `unavailable` (3 ardışık hata / `503`) | `Unavailable` | `error` | Yenilenebilir | Temizlenir / boş panel | Runtime önizlemesi geçici olarak alınamıyor. |
| `schema_unsupported` (`422` / sürüm uyumsuz) | `Schema unsupported` | `error` | Yenilenebilir | Temizlenir | Bu Studio sürümü gelen Runtime şema sürümünü okuyamıyor (fail-closed). |
| `host_disconnected` (ağ hatası) | `Host disconnected` | `error` | Pasif | Temizlenir | Yerel Studio Host bağlantısı kesildi (`hiyelx studio` çalışmıyor olabilir). |
| `capability_error` (`403` / geçersiz fragment) | `Access rejected` | `error` | Pasif | Temizlenir | Oturum erişim anahtarı geçersiz veya süresi doldu; Studio'yu CLI üzerinden yeniden başlatın. |

### 5.1. Oturum Değiştirme ve Tazeleme Değişmezleri
* Oturum seçimi değiştiğinde önceki oturumun `snapshot` verisi **anında temizlenir** (`host-client.js` monotonik generation koruması).
* Geç gelen eski istek yanıtları sessizce atılır; farklı bir oturumun verisi asla bayat yedek (stale fallback) olarak kullanılmaz.
* Canlı ekranda tüm zaman damgaları / yaş gösterimleri (`Updated Xs ago`) `host-client.js` içindeki monotonik saatle hesaplanır.

---

## 6. Dosya Mimarisi ve Küçük Doğrulanabilir Codex Görevleri

P3 tek bir büyük değişiklik yerine 6 küçük, bağımsız doğrulanabilir dilimde uygulanır:

### Görev `P3.1` — Canlı Giriş Varlıkları (`studio/live.html` ve `studio/live-app.js`)
* **Oluşturulacak dosyalar:** `studio/live.html`, `studio/live-app.js`
* **Dokunulması yasak dosyalar:** `studio/index.html`, `studio/studio.css`, `studio/fixtures.js`, `studio/app.js`
* **Sorumluluk:** `live.html` içinde yalnızca `studio.css`, `host-client.js` ve `live-app.js` yüklemesi; `live-app.js` içinde `HiyelxStudioHostClient.createController` bağlanması, oturum seçici, yenileme düğmesi, 10 canlı durumun deterministik DOM eşlemesi ve XSS-güvenli (`textContent`) render.
* **Doğrulama:** `tests/studio/test_live_composition.py` (Node VM / jsdom veya saf DOM mock ile tüm durum geçişleri + `fixtures.js` yokluğu kanıtı) + `tests/studio/test_p1_preservation.py`.

### Görev `P3.2` — Host, Launcher ve Wheel Paketleme Kompozisyonu
* **Güncellenecek dosyalar:** `src/hiyelx/studio/host.py`, `src/hiyelx/studio/launcher.py`, `pyproject.toml`
* **Sorumluluk:** `_STATIC_ROUTES` içine `/live` ve `/live-app.js` eklenmesi; `STUDIO_ASSET_NAMES` ve `wheel.force-include` içine `live.html` ve `live-app.js` eklenmesi; `StudioHost.launch_url` hedefinin `f"{self.origin}/live#capability={capability}"` olarak güncellenmesi (`GET /` statik P1 olarak korunur).
* **Doğrulama:** `tests/unit/studio/test_host.py`, `tests/unit/studio/test_launcher.py`, `tests/studio/test_p1_preservation.py`.

### Görev `P3.3` — Salt-Okunur Runtime Paket & Bileşen Keşif Ucu (`/api/v1/runtime/info`)
* **Güncellenecek dosyalar:** `src/hiyelx/studio/application.py`, `src/hiyelx/studio/host.py`, `studio/host-client.js` (yalnızca opsiyonel `fetchRuntimeInfo()` okuyucu metodu, mevcut kontratı kırmadan)
* **Sorumluluk:** `get_runtime_info()` adaptörü (kurulu paket sürümü, desteklenen şema sürümleri, yerleşik bileşen kayıt özeti — donanım veya kullanıcı modülü yüklemeden) ve `/api/v1/runtime/info` rotası (`X-HIYELX-Studio-Capability`, `421`/`403`/`405`, max 32 KB).
* **Doğrulama:** `tests/unit/studio/test_application.py`, `tests/unit/studio/test_host.py`, `tests/studio/test_host_client.py` (contract + security testleri).

### Görev `P3.4` — Canlı UI Runtime Bilgisi ve Uyumsuzluk Göstergesi
* **Güncellenecek dosyalar:** `studio/live.html`, `studio/live-app.js`
* **Sorumluluk:** Başlangıçta `/api/v1/meta` + `/api/v1/runtime/info` + `/api/v1/sessions` okunması; kurulu Runtime sürümü, desteklenen şemalar ve kayıtlı yerleşik modellerin salt-okunur bilgi kartında gösterilmesi; şema uyumsuzluğunda `schema_unsupported` fail-closed paneli.
* **Doğrulama:** `tests/studio/test_live_composition.py` + erişilebilirlik (`aria-live`, `role="status"`, klavye odak) kontrolleri.

### Görev `P3.5` — Uçtan Uca Canlı Runtime + Studio Host Entegrasyon Testi
* **Güncellenecek / eklenecek dosyalar:** `tests/integration/test_studio_host.py` (veya `tests/integration/test_studio_live_p3.py`)
* **Sorumluluk:** Gerçek `RuntimeOperations` + `LocalControlServer` + `StudioHost` üzerinde `/live`, `/api/v1/meta`, `/api/v1/runtime/info`, `/api/v1/sessions`, `/api/v1/sessions/{session}/preview` akışı; Runtime kapanınca `session_not_running` geçişi; Host kapanınca Runtime'ın çalışmaya devam etmesi ve sıfır artefakt mutasyonu kanıtı.
* **Doğrulama:** `TMPDIR=/tmp uv run pytest tests/integration/test_studio_host.py tests/studio/`.

### Görev `P3.6` — Kurulu Wheel (Non-Editable) P3 Kabul Doğrulaması
* **Eklenecek / güncellenecek dosyalar:** `tests/unit/studio/test_launcher.py` veya `scripts/verify_studio_p3.py`
* **Sorumluluk:** Temiz non-editable wheel kurulumunda kaynak ağacı olmadan `hiyelx studio` varlık staging'inin, `/live` + `/api/v1/runtime/info` + `/api/v1/sessions` yanıtlarının ve P1 SHA-256 korumasının uçtan uca doğrulanması.
* **Doğrulama:** `uv run ruff check . && uv run pyright && TMPDIR=/tmp uv run pytest`.

---

## 7. P3 Kabul Kriterleri ve 7 Kategorili Test Matrisi

P3 yalnızca aşağıdaki 6 kabul kriterinin tamamı otomatik kanıtla geçtiğinde tamamlanmış sayılır (ve P4'e geçiş kilidi açılır):

1. Kurulu (non-editable) `hiyelx` wheel paketinden tüm Studio varlıkları kaynak ağacı sızıntısı olmadan başarıyla keşfedilir ve `0o700`/`0o600` izinlerle sahnelenir.
2. `127.0.0.1` ephemeral port üzerindeki `StudioHost` canlı Runtime oturumuyla `#capability=` → `X-HIYELX-Studio-Capability` akışıyla konuşur.
3. Gerçek oturum listesi, Runtime paket/bileşen özeti, sağlık ve önizleme verileri canlı DOM'da (`/live`) doğru render edilir.
4. Runtime çalışmıyorken, oturum kapandığında, host koptuğunda veya şema uyumsuzken kontrollü hata/boş duruma geçilir; sahte veri gösterilmez.
5. `studio/live.html` hiçbir şekilde `fixtures.js` yüklemez; fikstür modu (`/`) ile canlı mod (`/live`) yapısal olarak ayrıdır.
6. P1 SHA-256 koruma testi (`test_p1_preservation.py`), P2 güvenlik testleri (`421`/`403`/`405`/CSP/sızıntısızlık), `ruff`, strict `pyright` ve tüm non-hardware `pytest` paketi sıfır hata ile geçer.

| Test Kategorisi | P3 Kanıt Hedefi |
|---|---|
| **Unit** | `get_runtime_info()` veri modeli ve hata eşlemeleri |
| **Component** | `live-app.js` 10 durumlu DOM render ve erişilebilirlik kontrolleri |
| **Contract** | `/api/v1/meta`, `/sessions`, `/preview`, `/runtime/info` tam anahtar kümesi ve 11 hata üçlüsü |
| **Integration** | Canlı `LocalControlServer` + `StudioHost` + süreç kapanış bağımsızlığı + kurulu wheel |
| **E2E** | Başlat → keşfet → oturum seç → canlı veri oku → oturum durdur → hata durumunu doğrula |
| **Security** | Fragment silme, `421` Host, `403` Origin/Capability, `405` OPTIONS/POST, sıfır token/yol sızıntısı |
| **Regression** | `tests/studio/test_p1_preservation.py` (byte-identical P1) + tüm P2 testleri CI'da kesintisiz yeşil |
