#!/usr/bin/env bash
# Full pipeline, end to end, from an empty checkout.
set -euo pipefail
cd "$(dirname "$0")"
for step in 01_generate_data.py 02_map_enrollments.py 03_select_dataset.py; do
  echo; echo "=================== $step ==================="; python3 "$step"
done
for product in cumin wheat; do
  echo; echo "=================== 04_build_indices.py --product $product ==================="
  python3 04_build_indices.py --product "$product"
  echo; echo "=================== 05_price_product.py --product $product ==================="
  python3 05_price_product.py --product "$product"
done
echo; echo "=================== 06_cyclone_cover.py ==================="; python3 06_cyclone_cover.py
echo; echo "=================== 07_figures.py ==================="; python3 07_figures.py
