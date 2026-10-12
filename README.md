# OSM Countries GeoJSON

Country boundaries from OpenStreetMap, simplified and exported as GeoJSON.

**[Browse and download the files](https://osm-countries-geojson.monicz.dev/)**

Choose a simplification tolerance to suit your map: smaller numbers preserve more
detail. Downloads are available in Zstandard, Brotli and gzip formats.
Original OpenStreetMap tags are retained in each feature's `properties.tags`.

```sh
curl --fail --location --output countries.geojson.zst \
  https://osm-countries-geojson.monicz.dev/osm-countries-0-001.geojson.zst
zstd --decompress countries.geojson.zst
```

Generation is scheduled twice daily. The download index shows the source timestamp
of the published data; failed updates leave the last complete release available.

Used by [OpenAEDMap](https://openaedmap.org).

## License and support

The generator is licensed under [AGPL-3.0](LICENSE). The data is licensed under
[ODbL 1.0](https://opendatacommons.org/licenses/odbl/), with attribution to
[OpenStreetMap contributors](https://www.openstreetmap.org/copyright).

[GitHub Sponsors](https://github.com/sponsors/Zaczero) ·
[Liberapay](https://liberapay.com/Zaczero/) ·
[Contact](https://monicz.dev/#get-in-touch)
