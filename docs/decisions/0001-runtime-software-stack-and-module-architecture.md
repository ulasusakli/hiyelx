# ADR 0001: HIYELX Runtime Software Stack, 12-Module Architecture, and Scope Boundaries

* **Status:** Accepted
* **Date:** 2026-11-22
* **Authors:** HIYELX Core Architecture Team
* **Target Release:** Runtime V1 (Foundation) → V1.5 (Expansion) → V2 (Platform)

---

## Context

Robotik sistemlerde uygulama geliştiricileri; paket bağımlılıkları, dağınık bileşenler, üreticiye özel SDK'lar ve simülasyon-donanım uyumsuzlukları nedeniyle donanıma bağımlı kod yazmak zorunda kalmaktadır. 

HIYELX'in temel tezi **"Donanımı değiştir, uygulamayı değil" (Change the hardware, not the application)** ilkesidir. Bu hedefi gerçekleştirmek için basit bir kontrol kütüphanesinin ötesinde, heterojen robotik bileşenleri ortak bir sözleşme, yaşam döngüsü ve yürütme (execution) modeli altında toplayan modüler bir **Robotics Execution Platform** gerekmektedir.

Ayrıca HIYELX Studio (gözlem ve geliştirme arayüzü) ile HIYELX Runtime (robot üzerinde çalışan yürütme motoru) arasında katı bir mimari ayrım kabul edilmiştir: **Studio robotu tasarlar ve izler; Runtime ise robotu gerçekten çalıştırır ve donanıma erişen tek yetkili otoritedir.**

---

## Decisions

### 1. Programlama Dili ve Çok Katmanlı Teknoloji Tercihi
* **Birincil Dil (Primary / Core): Python 3.12+**
  * Runtime Kernel, Konfigürasyon, Yaşam Döngüsü (Lifecycle), Bileşen Yönetimi (Component Management), Süreç İçi Olay Dağıtımı (In-Process Event Bus) ve Yerel API Host Python 3.12 üzerinde geliştirilecektir.
  * Python; zengin tip desteği (`typing`, `Protocol`), `asyncio` asenkron I/O yetenekleri, Pydantic v2 veri bütünlüğü ve ROS 2 Jazzy (Ubuntu 24.04 LTS / Mayıs 2029) ekosistem uyumluluğu nedeniyle ana orkestrasyon dili olarak seçilmiştir.
* **Seçici Yerel Performans Katmanı (Selective Native Execution): Rust / C++**
  * Tüm sistemi C++ ile yazmak geliştirici ergonomisini ve modülerliği zayıflatır; tüm sistemi Python ile yazmak ise sert zamanlama garantisi gerektiren alt seviye döngülerde yetersiz kalır.
  * C++ / Rust yalnızca sert gerçek zamanlı (hard real-time) kontrol, yüksek frekanslı sinyal işleme veya doğrudan donanım kütüphaneleri gerektiğinde izole C-ABI / PyO3 / CFFI sınırları ardında kullanılacaktır.
* **Veri Doğrulama ve Sözleşmeler:** Pydantic v2 + JSON Schema.
* **Konfigürasyon:** YAML (Strict, Fail-closed validation).
* **API Framework:** Starlette / FastAPI tabanlı yerel `127.0.0.1` typed JSON HTTP API.
* **Statik Analiz ve Kalite Kapısı:** `pyright` (strict mode), `ruff`, `pytest` + `pytest-asyncio`.
* **Gözlemlenebilirlik (Observability):** `structlog` / yapılandırılmış loglar + OpenTelemetry (metrics & tracing).

### 2. Sistem Mimarisi: 12 Modüllü Katmanlı Yapı
Runtime Core, dağıtık mikroservis karmaşıklığından kaçınmak amacıyla başlangıçta **Modüler Monolit (Modular Monolith)** olarak yapılandırılacaktır. 12 ana modül:

1. **Module 01 — Runtime Kernel:** Bootstrap, Context, Lifecycle (`CREATED` → `STARTING` → `RUNNING` → `STOPPING` → `STOPPED` / `FAILED`), Bağımlılık Çözücü (DAG Resolver), Kontrollü Kapatma (Graceful Shutdown).
2. **Module 02 — Configuration & Robot Description:** `robot:`, `runtime:`, `devices:`, `components:`, `applications:` hiyerarşisi, ortam profilleri, şema versiyonlama.
3. **Module 03 — Component & Plugin Framework:** Standart `Component` sözleşmesi (`id`, `category`, `capabilities`, `lifecycle`, `health`), Python `entry_points` tabanlı keşif, wheel dağıtımı.
4. **Module 04 — Device & Driver Framework:** Cihaz yönetimi, donanım kaynak kilitleme (port/USB conflict detection), yetenek tabanlı HAL (`CAN_SET_VELOCITY`, `CAN_STREAM_FRAMES` vb.).
5. **Module 05 — Communication & Data Infrastructure:** Süreç içi tipli mesaj/olay veri yolu (In-process typed event bus), pub/sub, komut dağıtıcısı, QoS parametreleri.
6. **Module 06 — Application & Execution Manager:** Çoklu bileşenleri koşturan robot uygulamaları, çalışma denetimi (supervision).
7. **Module 07 — Robotics Services Framework:** `MotionService`, `SensorService`, `VisionService` gibi üst seviye algoritmik servisler.
8. **Module 08 — State, Resource & Health Management:** Üçlü durum modeli:
   - **Desired State:** Algoritmanın veya kullanıcının talep ettiği durum.
   - **Actual State:** Sensörden/enkoderden okunan fiziksel gerçeklik.
   - **Health State:** Operasyonel sağlık (`HEALTHY`, `DEGRADED`, `UNHEALTHY`).
9. **Module 09 — Fault Management & Safety Infrastructure:** Hata taksonomisi, geri alma (rollback), bileşen izolasyonu, yazılımsal acil durdurma koordinasyonu (`safe_stop`).
10. **Module 10 — API Host, Security & External Interfaces:** `127.0.0.1` loopback bağlama, URL fragment capability token, tek oturum yönetimi, Studio ve CLI arayüzü.
11. **Module 11 — Observability & Diagnostics:** Yapılandırılmış loglar, metrikler, trace ID takibi, tanılama raporları.
12. **Module 12 — Integration, Simulation & Ecosystem:** V2 kapsamında harici adaptörler: ROS 2 / DDS adaptörü, Gazebo / MuJoCo köprüsü, ONNX AI inference.

### 3. Teslimat Kapsam Sınırları (Delivery Scopes)
* **V1 (Core Runtime / Must Have):**
  - Modül 1–5, 8–11 temel düzeyde tamamlanacak.
  - 4 kanonik sanal bileşen (`MockMotor`, `MockEncoder`, `MockCamera`, `MockIMU`) ve en az 1 referans fiziksel motor sürücüsü (DYNAMIXEL XL430).
  - Süreç içi tipli haberleşme, yerel HTTP API, Studio salt-okunur canlı izleme.
  - ROS 2, DDS, cloud telemetri ve harici mikroservisler V1 kapsamı dışındadır.
* **V1.5 (Expansion):**
  - Ek donanım sürücüleri (USB Kamera, Seri IMU), temel hareket/görüntü servisleri, süreç izolasyonu (process isolation).
* **V2 (Advanced Platform):**
  - ROS 2 / DDS adaptörleri, Gazebo/MuJoCo köprüsü, dağıtık haberleşme, çoklu robot temelleri, bulut filo telemetrisi.

---

## Consequences

### Pozitif Sonuçlar
* **Geliştirici Bağımsızlığı:** Uygulamalar donanım marka ve protokollerinden tamamen izole edilir.
* **Öngörülebilir Güvenlik ve Kararlılık:** Deterministik durum makinesi, Kahn algoritmalı DAG sıralaması ve üçlü durum ayrımı ile yarış durumları (race conditions) ve çökmeler önlenir.
* **Kademeli Karmaşıklık:** Dağıtık sistem maliyetleri (DDS, gRPC RPC karmaşası, ağ gecikmesi) V1 çekirdeğine sokulmaz; süreç içi hafif ve hızlı bir veri yolu kullanılır.
* **Tek Yetkili Otorite:** Studio asla doğrudan donanıma dokunamaz; tüm operasyonlar Runtime API üzerinden doğrulanıp yetkilendirilir.

### Negatif Sonuçlar ve Yönetilmesi Gereken Riskler
* **Sert Gerçek Zamanlılık (Hard Real-Time):** Python asyncio 1 kHz döngü frekansını garanti edemez. Bu sınır açıkça kabul edilmiştir; alt seviye döngüler mikrokontrolör (MCU) veya yerel HAL katmanında koşacaktır.
* **Yazılımsal Güvenlik Sınırı:** Runtime bir güvenlik PLC'si (ISO 13849 SIL3/PLe) değildir. Acil durdurma ve güç kesme daima bağımsız fiziksel devrelerle sağlanmalıdır.
