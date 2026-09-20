# Családi tárhely TrueNAS SCALE rendszerre

Egyszerű, reszponzív, sötét webes fájlkezelő. A FastAPI kizárólag a `SHARED_ROOT` alatt dolgozik; az API és a felület csak relatív útvonalakat lát. A backend a loopback címen fut, az Nginx szolgálja ki a React buildet. Konténeres telepítésnél a HTTPS-t a Cloudflare Tunnel, a régi systemd telepítési mintában maga az Nginx terminálja.

## Ajánlott: konténeres telepítés TrueNAS SCALE 24.10+ alatt

Ehhez **nem kell Python virtualenv, Node.js vagy Nginx telepítése a NAS alaprendszerére**. A [Dockerfile](Dockerfile) a Reactet és a FastAPI-t két külön image-be építi, a [compose.yaml](compose.yaml) pedig a TrueNAS Apps „Install via YAML” felületére másolható. A korábbi, kézi systemd telepítés lejjebb alternatívaként megmaradt.

1. A TrueNAS **Datasets** felületén hozd létre a `tank/family_share` datasetet az adatoknak, valamint például `tank/apps/family-share` datasetet a projektfájloknak. A projekt nem a megosztott datasetben van. Az **Apps** oldalon válassz Apps poolt, ha még nincs beállítva. Más poolnév esetén a Compose fájl három host path-ját is írd át.
2. A TrueNAS **Credentials > Local Users/Groups** alatt hozz létre egy dedikált `familyshare` usert és csoportot, például UID/GID `3001:3001` értékkel, shell login nélkül. A `family_share` dataset ACL-jében ennek a usernek/csoportnak adj traverse/read/write/modify jogot, az `other` csoportnak ne. A projekt datasethez csak olvasási/traverse jog kell futáskor, de image buildkor a TrueNAS Apps/Docker szolgáltatásnak látnia kell a forrást. Ha más UID/GID-t választasz, módosítsd a `user: "3001:3001"` sort a Compose fájlban.
3. Másold a projektet a `/mnt/tank/apps/family-share` mappába. A `.env.example` alapján hozz létre ott egy `.env` fájlt. Az Argon2 hashhez, ha a NAS-on nincs Python környezeted, az image elkészülte után használd az 5. pont egyparancsos generátorát.
4. Az `.env` minimális éles tartalma:

   ```dotenv
   SHARED_ROOT=/mnt/tank/family_share
   APP_SECRET=ide-egy-openssl-rand-hex-32-kimenete
   ADMIN_USERNAME=family
   ADMIN_PASSWORD_HASH='$argon2id$v=19$m=65536,t=3,p=4$...'
   SESSION_HOURS=24
   COOKIE_SECURE=true
   PUBLIC_ORIGIN=https://files.example.com
   ```

   A hash körüli **egyszeres idézőjelek fontosak**: a Docker Compose különben értelmezheti a `$` karaktereket. Az `APP_SECRET` legalább 32 karakter legyen; `openssl rand -hex 32` jó értéket ad. A `.env` ne kerüljön Gitbe, és lehetőleg csak admin olvashassa. A konténeren belül a `SHARED_ROOT` automatikusan `/data` lesz, ezt a Compose `environment` felülírja; a hoston továbbra is a `/mnt/tank/family_share` az adat helye.
5. A TrueNAS **Apps > Discover > ⋮ > Install via YAML** felületen az app neve legyen például `family-share`; másold be a teljes [compose.yaml](compose.yaml) tartalmát, ellenőrizd a host pathokat/UID-t/portot, majd Save. Az első build letölti a Python/Node/Nginx image-eket és az npm/Python függőségeket, de a NAS rendszerére nem telepít csomagot. A helyi CLI alternatíva: `cd /mnt/tank/apps/family-share && docker compose up -d --build`.

   Ha még nincs jelszóhashed, először egy tetszőleges placeholderrel készítsd el az `.env`-et, építsd meg az image-et, majd a NAS shellben:

   ```bash
   cd /mnt/tank/apps/family-share
   docker compose run --rm --no-deps backend python backend/scripts/hash_password.py
   ```

   A kapott teljes hash kerüljön a `.env`-be az egyszeres idézőjelek közé, majd `docker compose up -d --force-recreate backend`. A TrueNAS UI-ból indított app esetén szükség lehet az app újraindítására vagy a YAML mentésére, hogy az új env érték életbe lépjen.
6. A webes port alapból `18080` a NAS LAN-címén. **Ne nyisd ki a routeren.** Cloudflare Tunnelben a `files.example.com` hostname Service URL-je `http://NAS_LAN_IP:18080` legyen. A böngésző HTTPS-en érkezik Cloudflare-hez; a Tunnel és az app közötti helyi LAN-hop HTTP. Ha a `cloudflared` ugyanazon host hálózati névterében fut, a Compose portját korlátozhatod `127.0.0.1:18080:8080`-ra és a Tunnel `http://127.0.0.1:18080` URL-t használhat. A tunnel ne a backend `8000` portjára mutasson, mert ott nincs frontend.
7. Ellenőrizd a TrueNAS **Apps > Installed > family-share > Logs** oldalon, hogy mindkét szolgáltatás fut. A `http://NAS_LAN_IP:18080/api/auth/me` bejelentkezés nélkül várt válasza `401`. Mivel `COOKIE_SECURE=true`, a bejelentkezést a `https://files.example.com` címen teszteld, nem a LAN HTTP címen.

A `backend` konténer `127.0.0.1:8000`-en hallgat a **két konténer közös hálózati névterében**; ezt a portot a Compose nem publikálja. Csak az Nginx `8080` portja jelenik meg a NAS `18080` portján. A backend nem-root UID/GID-vel fut, a konténer root filesystemje csak olvasható, és kizárólag a `/data` bind mount írható. A nagy multipart feltöltések spoolja a dataseten lévő, API-ból tiltott `/data/.family-share-tmp` könyvtárba kerül; ezt induláskor a backend hozza létre `0700` móddal. Számolj azzal, hogy feltöltéskor a spool és a végleges fájl egy ideig egyszerre foglal helyet ugyanazon a dataseten.

**Cloudflare méretkorlát:** a konténer nem kerüli meg a Cloudflare publikus proxy/Tunnel egy kérésre vonatkozó feltöltési limitjét (Free/Pro csomagban jelenleg 100 MB). Több GB-os feltöltéshez később chunkolt upload API kell, vagy Cloudflare proxy nélküli/VPN-es útvonal. A meglévő letöltés és videó Range streaming ettől független.

Megjegyzés: a konténeres Nginx HTTP-n figyel a NAS-on; HTTPS-t ebben a felállásban a Cloudflare terminálja. Ha közvetlen publikus elérést szeretnél Cloudflare nélkül, külön HTTPS reverse proxy és tanúsítvány kell. Az alábbi rendszer-Nginx/systemd fejezet másik telepítési mód, a Compose telepítésnél nem szükséges.

## Funkciók és biztonsági modell

- Argon2id jelszóhash, rövid életű aláírt session JWT egy `HttpOnly`, `Secure`, `SameSite=Strict` cookie-ban.
- CSRF token és `Origin` ellenőrzés minden módosító kérésen.
- Könyvtárlista, többfájlos drag-and-drop feltöltés, progress, letöltés, új mappa, átnevezés és megerősített törlés.
- Folyamatos mappaszintű képnéző előző/következő navigációval, natív teljes képernyős móddal, mobilos lapozással és 4 másodperces diavetítéssel; emellett videó- és PDF-előnézet. A letöltés és preview 1 MiB-os darabokban streamel; az egyetlen HTTP byte-range kéréseket `206 Partial Content` válasszal kezeli.
- Nincs publikus lista vagy fájlútvonal. Minden fájl végpont sessiont kér.
- Az útvonalkezelő elutasítja az abszolút pathot, `..`, backslash és NUL karaktert. Minden létező komponenst symlinkre ellenőriz, majd minden fájlművelet előtt `resolve()` után ellenőrzi, hogy a cél a kanonikus root alatt van. A symlinkek szándékosan nem követhetők, akkor sem, ha befelé mutatnak.
- A feltöltés nem kerül egyben memóriába: a multipart parser spoololt fájlt használ, az alkalmazás pedig 1 MiB-os darabokban ír ugyanazon dataset ideiglenes fájljába, majd atomikusan nevezi át.
- A mappatörlés csak üres mappára működik, így egy téves kattintás nem töröl rekurzívan teljes fákat.

Megjegyzés: a hagyományos path-alapú Linux fájlműveleteknél egy másik, ugyanazon dataseten írási joggal rendelkező helyi folyamat elméletileg versenyhelyzetet okozhat az ellenőrzés és a művelet között. A dataset írási jogát ezért kizárólag a szolgáltatáscsoportnak és a megbízható adminoknak add; ne engedd, hogy nem megbízható helyi felhasználó symlinkeket cserélgessen benne.

## Fejlesztői indítás

Python 3.11+ és Node.js 20+ ajánlott.

```bash
cp .env.example .env
python3 -m venv backend/.venv
backend/venv/bin/pip install -r requirements.txt
backend/venv/bin/python backend/scripts/hash_password.py
# Másold a kapott teljes $argon2id$... sort az .env ADMIN_PASSWORD_HASH értékébe.
backend/venv/bin/uvicorn backend.main:app --host 127.0.0.1 --port 8000 --reload
```

Másik terminálban:

```bash
cd frontend
npm install
npm run dev
```

Lokális, HTTP-s fejlesztésnél állítsd `COOKIE_SECURE=false` értékre és `PUBLIC_ORIGIN=http://localhost:5173`-ra. Éles környezetben ezeket állítsd vissza.

## TrueNAS SCALE telepítés

Az alábbi példa szerint a forrás `/opt/family-share`, az adat pedig ettől elkülönülve `/mnt/tank/family_share`. A pool nevét igazítsd a rendszeredhez. A SCALE rendszerfrissítése érintheti az alaprendszerbe kézzel telepített csomagokat és service fájlokat; frissítés előtt legyen másolatod a projektből, `.env`-ből és a service/Nginx konfigurációból.

### 1. Dataset

A TrueNAS webes felületén nyisd meg a **Datasets** oldalt, válaszd a `tank` poolt, majd **Add Dataset**:

- Name: `family_share`
- Share Type: Generic
- Case Sensitivity: Sensitive (ajánlott)

Az eredmény:

```text
/mnt/tank/family_share
```

Ne tedd a projektet ebbe a datasetbe. Snapshotot és mentést magára a `family_share` datasetre állíts be.

### 2. Külön user/group és ACL

A TrueNAS webes felületén hozz létre egy `familyshare` csoportot és ugyanilyen nevű, bejelentkezésre nem használható system usert. Jegyezd fel a választott UID/GID-t (például mindkettő `3001`). A dataset **Edit Permissions / ACL** nézetében:

- owner user: `familyshare` (`UID 3001`)
- owner group: `familyshare` (`GID 3001`)
- a tulajdonos és csoport kapjon traverse/read/write/modify jogot;
- az `other` ne kapjon jogot;
- alkalmazd rekurzívan csak akkor, ha a dataset új vagy biztosan ezt akarod a már meglévő fájlokra.

Shellből POSIX jogosultság esetén az egyenértékű példa:

```bash
chown -R familyshare:familyshare /mnt/tank/family_share
chmod 2770 /mnt/tank/family_share
```

A `2` setgid bit miatt az új elemek a `familyshare` csoportot öröklik. ACL datasetnél a webes ACL szerkesztőt használd, ne keverd gondolkodás nélkül a POSIX `chmod`-dal. Az Nginxnek nincs szüksége dataset-hozzáférésre.

### 3. Projekt és virtualenv

Másold vagy klónozd a projektet `/opt/family-share` alá, majd:

```bash
cd /opt/family-share
python3 -m venv backend/.venv
backend/.venv/bin/pip install --upgrade pip
backend/.venv/bin/pip install -r requirements.txt
chown -R root:root /opt/family-share
chmod -R o-w /opt/family-share
```

A backend forrás és virtualenv így nem írható a szolgáltatás userének. Futás közbeni alkalmazásadat nincs a projektben; kizárólag a dataset változik.

### 4. `.env`

```bash
cd /opt/family-share
cp .env.example .env
openssl rand -hex 32
backend/.venv/bin/python backend/scripts/hash_password.py
```

Szerkeszd a `.env`-et:

```dotenv
SHARED_ROOT=/mnt/tank/family_share
APP_SECRET=az-openssl-altal-generalt-legalabb-32-karakteres-titok
ADMIN_USERNAME=family
ADMIN_PASSWORD_HASH=$argon2id$v=19$m=65536,t=3,p=4$...
SESSION_HOURS=24
COOKIE_SECURE=true
PUBLIC_ORIGIN=https://files.example.com
```

Kézi (nem Compose) telepítésnél az Argon2 hash dollárjeleit nem kell escape-elni. Compose használatakor viszont tedd a teljes hash értékét egyszeres idézőjelek közé a fenti konténeres rész szerint. Védd a titkokat:

```bash
chown root:familyshare /opt/family-share/.env
chmod 640 /opt/family-share/.env
```

### 5. Frontend build

Telepített Node.js/npm mellett:

```bash
cd /opt/family-share/frontend
npm install
npm run build
```

Az Nginxnek olvasási/traverse joga kell az `/opt/family-share/frontend/dist` könyvtárhoz. A forrás tulajdonosa továbbra is root legyen.

### 6. systemd

A mellékelt [deploy/family-share.service](deploy/family-share.service) szolgáltatás nem-root userrel, kizárólag `127.0.0.1:8000` címen indul. A `ProtectSystem=strict` és a `ReadWritePaths=/mnt/tank/family_share` együtt megakadályozza, hogy máshova írjon. Ha más pool/dataset nevet használsz, a service fájlban is módosítsd a `ReadWritePaths` értékét.

```bash
cp /opt/family-share/deploy/family-share.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now family-share
systemctl status family-share
journalctl -u family-share -n 100 --no-pager
curl -i http://127.0.0.1:8000/api/auth/me
```

Az utolsó kérés várt válasza `401`, mert nincs session; ez igazolja, hogy az API él és védett. A két worker külön folyamat, de a JWT session állapotmentes, ezért megosztott session-adatbázis nem kell.

### 7. Nginx reverse proxy és nagy fájlok

Telepítsd/engedélyezd az Nginxet a SCALE környezeted támogatott adminisztrációs módján, majd másold a [deploy/nginx-files.example.com.conf](deploy/nginx-files.example.com.conf) fájlt az aktív Nginx konfigurációs könyvtárba. Ellenőrzés és újratöltés:

```bash
nginx -t
systemctl reload nginx
```

A minta:

- a React `dist` könyvtárat szolgálja ki;
- csak az `/api/` útvonalat proxyzza a localhost backendhez;
- kikapcsolja a request/response bufferinget és egyórás timeoutot ad;
- nem korlátozza Nginx szinten a body méretét (`client_max_body_size 0`);
- továbbítja a `Range` headert alapértelmezés szerint; a FastAPI küldi az `Accept-Ranges` és `Content-Range` fejléceket;
- tartalmazza az Upgrade/Connection headereket, bár a jelenlegi alkalmazás nem igényel WebSocketet.

Az unlimited upload helyett éles használatban célszerű a rendelkezésre álló tárhelyhez illő felső korlátot megadni, például `client_max_body_size 20G`.

### 8. Domain és HTTPS

Hozz létre DNS `A`/`AAAA` rekordot a `files.example.com` névhez. Internetes elérésnél a routeren csak a 80/443 portot irányítsd az Nginx hostjára; a 8000 portot soha. Let's Encrypt/Certbot példa:

```bash
certbot --nginx -d files.example.com
```

Ha a TrueNAS web UI maga használja a 80/443 portot, adj az Nginxnek külön IP-címet (alias/VLAN) vagy használj már meglévő, külön reverse proxy gépet. Ne állítsd le vakon a TrueNAS kezelőfelületét. Belső-only domainnél használhatsz saját CA-t, de a klienseszközöknek meg kell bízniuk benne; `COOKIE_SECURE=true` mellett valódi HTTPS szükséges.

### 9. Ellenőrzőlista

```bash
ss -ltnp | grep 8000
sudo -u familyshare test -w /mnt/tank/family_share
curl -I https://files.example.com
```

Ezután böngészőből:

1. jelentkezz be;
2. hozz létre mappát, tölts fel több fájlt drag-and-droppal;
3. próbálj képet, PDF-et és videót megnyitni, majd egy nagy fájlt letölteni;
4. ellenőrizd a DevTools Network panelen, hogy videó seeknél `206` és `Content-Range` érkezik;
5. ellenőrizd, hogy kijelentkezve minden `/api/files` és `/api/content` kérés `401`.

## API áttekintés

Az API mindenhol roothoz viszonyított POSIX pathot használ, például `photos/holiday.jpg`; soha nem ad vissza `/mnt/...` útvonalat. Fő végpontok: `/api/auth/login`, `/api/auth/me`, `/api/auth/logout`, `/api/files`, `/api/content`, `/api/upload`, `/api/folders`, `/api/rename`. Az interaktív API dokumentáció szándékosan ki van kapcsolva éles támadási felület csökkentésére.
