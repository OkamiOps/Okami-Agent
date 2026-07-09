---
name: maps
description: Geocodifica endereço, acha POI perto de um ponto, calcula rota/distância e timezone via OpenStreetMap/OSRM. Sem chave de autenticação, só stdlib.
triggers: [mapa, endereço, localização, geocodificar, rota, distância, direção, perto de mim, restaurante perto, farmácia perto, coordenadas, fuso horário]
intent_examples:
  - "acha um restaurante italiano perto do hotel"
  - "qual a distância de carro daqui até o aeroporto"
  - "me dá o endereço dessas coordenadas"
  - "como chego a pé até o museu"
  - "que farmácias tem perto desse CEP"
metadata:
  hermes:
    tags: [maps, geocoding, places, routing, distance, directions, nearby, location, openstreetmap, nominatim, overpass, osrm]
    category: productivity
    ported_from: hermes maps skill (Mibayy, MIT)
---

# Mapas

Inteligência de localização usando fontes de dado abertas e gratuitas. 8 comandos, 46 categorias de
POI, zero dependência externa (só stdlib do Python), sem autenticação necessária.

Fontes de dado: OpenStreetMap/Nominatim, Overpass API, OSRM, TimeAPI.io.

## Quando usar

- O dono manda um pin de localização no Telegram (latitude/longitude na mensagem) → `nearby`
- O dono quer coordenadas de um nome de lugar → `search`
- O dono tem coordenadas e quer o endereço → `reverse`
- O dono pede restaurante, hospital, farmácia, hotel etc. perto de algum ponto → `nearby`
- O dono quer distância/tempo de viagem de carro, a pé ou de bike → `distance`
- O dono quer instruções passo a passo entre dois lugares → `directions`
- O dono quer fuso horário de uma localização → `timezone`
- O dono quer buscar POIs dentro de uma área geográfica → `area` + `bbox`

## Pré-requisitos

Python 3.8+ (stdlib apenas — sem `pip install`).

```bash
MAPS=${OKAMI_SKILL_DIR}/scripts/maps_client.py
```

## Comandos

### search — geocodifica um nome de lugar

```bash
python3 $MAPS search "Torre Eiffel"
python3 $MAPS search "Av. Paulista, 1000, São Paulo"
```

Devolve: lat, lon, nome exibido, tipo, bounding box, score de importância.

### reverse — coordenadas → endereço

```bash
python3 $MAPS reverse 48.8584 2.2945
```

Devolve: endereço completo (rua, cidade, estado, país, CEP).

### nearby — acha lugares por categoria

```bash
# Por coordenadas (de um pin de localização do Telegram, por exemplo)
python3 $MAPS nearby 48.8584 2.2945 restaurant --limit 10
python3 $MAPS nearby 40.7128 -74.0060 hospital --radius 2000

# Por endereço/cidade/CEP/ponto de referência — --near geocodifica sozinho
python3 $MAPS nearby --near "Times Square, New York" --category cafe
python3 $MAPS nearby --near "90210" --category pharmacy

# Múltiplas categorias numa query só
python3 $MAPS nearby --near "downtown austin" --category restaurant --category bar --limit 10
```

46 categorias: `restaurant, cafe, bar, hospital, pharmacy, hotel, guest_house, camp_site,
supermarket, atm, gas_station, parking, museum, park, school, university, bank, police,
fire_station, library, airport, train_station, bus_stop, church, mosque, synagogue, dentist,
doctor, cinema, theatre, gym, swimming_pool, post_office, convenience_store, bakery, bookshop,
laundry, car_wash, car_rental, bicycle_rental, taxi, veterinary, zoo, playground, stadium,
nightclub`.

Cada resultado tem: `name`, `address`, `lat`/`lon`, `distance_m`, `maps_url` (link clicável do
Google Maps), `directions_url` (rota do Google Maps a partir do ponto de busca), e tags quando
disponíveis — `cuisine`, `hours` (horário de funcionamento), `phone`, `website`.

### distance — distância e tempo de viagem

```bash
python3 $MAPS distance "Paris" --to "Lyon"
python3 $MAPS distance "New York" --to "Boston" --mode driving
python3 $MAPS distance "Big Ben" --to "Tower Bridge" --mode walking
```

Modos: `driving` (default), `walking`, `cycling`. Devolve distância por estrada, duração e
distância em linha reta pra comparação.

### directions — instruções passo a passo

```bash
python3 $MAPS directions "Torre Eiffel" --to "Museu do Louvre" --mode walking
python3 $MAPS directions "Aeroporto JFK" --to "Times Square" --mode driving
```

Devolve passos numerados com instrução, distância, duração, nome da via e tipo de manobra
(virar, partir, chegar etc.).

### timezone — fuso horário de uma coordenada

```bash
python3 $MAPS timezone 48.8584 2.2945
python3 $MAPS timezone 35.6762 139.6503
```

Devolve nome do fuso, offset UTC e hora local atual.

### area — bounding box e área de um lugar

```bash
python3 $MAPS area "Manhattan, New York"
python3 $MAPS area "Londres"
```

Devolve as coordenadas do bounding box, largura/altura em km e área aproximada. Útil como entrada
pro comando `bbox`.

### bbox — busca dentro de um bounding box

```bash
python3 $MAPS bbox 40.75 -74.00 40.77 -73.98 restaurant --limit 20
```

Acha POIs dentro de um retângulo geográfico. Rode `area` primeiro pra pegar as coordenadas do
bounding box de um lugar nomeado.

## Trabalhando com pin de localização do Telegram

Quando o dono manda um pin de localização, a mensagem tem campos `latitude:` e `longitude:`.
Extraia esses valores e passe direto pro `nearby`:

```bash
# Dono mandou um pin em 36.17, -115.14 e perguntou "acha cafés perto"
python3 $MAPS nearby 36.17 -115.14 cafe --radius 1500
```

Apresente os resultados como lista numerada com nome, distância e o campo `maps_url` pra virar um
link clicável no chat. Pra perguntas tipo "tá aberto agora?", confira o campo `hours`; se estiver
ausente ou pouco claro, verifique com a skill de busca web já que horário no OSM é mantido pela
comunidade e nem sempre está atualizado.

## Exemplos de fluxo

**"Acha restaurante italiano perto do Coliseu"**:
`nearby --near "Colosseum Rome" --category restaurant --radius 500` — um comando só, geocodifica
sozinho.

**"O que tem perto desse pin que mandaram?"**: extraia lat/lon da mensagem do Telegram → `nearby
LAT LON cafe --radius 1500`.

**"Como vou a pé do hotel até o centro de convenções?"**: `directions "Nome do Hotel" --to "Centro
de Convenções" --mode walking`.

**"Que restaurante tem no centro de Seattle?"**: `area "Downtown Seattle"` → pega o bounding box →
`bbox S W N E restaurant --limit 30`.

## Armadilhas

- Termos de uso do Nominatim: máximo 1 req/s (o script já respeita isso sozinho)
- `nearby` precisa de lat/lon OU `--near "<endereço>"` — um dos dois é obrigatório
- Cobertura de rota do OSRM é melhor pra Europa e América do Norte
- A Overpass API pode ficar lenta em horário de pico; o script já cai automaticamente pro mirror
  seguinte (`overpass-api.de` → `overpass.kumi.systems`)
- `distance` e `directions` usam a flag `--to` pro destino (não é posicional)
- Se um CEP sozinho der resultado ambíguo, inclua país/estado

## Verificação

```bash
python3 ${OKAMI_SKILL_DIR}/scripts/maps_client.py search "Statue of Liberty"
# Deve devolver lat ~40.689, lon ~-74.044

python3 ${OKAMI_SKILL_DIR}/scripts/maps_client.py nearby --near "Times Square" --category restaurant --limit 3
# Deve devolver uma lista de restaurantes a ~500m da Times Square
```
