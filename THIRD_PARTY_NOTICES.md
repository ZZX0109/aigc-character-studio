# Third party asset attribution

The bundled base head is derived from the Lee Perry-Smith scan, distributed in
the official three.js examples (r180).

- Creator: Lee Perry-Smith / Infinite-Realities
- License: Creative Commons Attribution 3.0 Unported (CC BY 3.0)
- Original project: https://www.triplegangers.com/
- Source asset: https://github.com/mrdoob/three.js/blob/r180/examples/models/gltf/LeePerrySmith/LeePerrySmith.glb
- License text: data/base-face/source/LeePerrySmith_License.txt

This project converts the source mesh into a canonical coordinate system and
applies a deterministic local nasal-ala deformation. The scan is a static test
asset, not a FLAME model, facial rig, synthetic identity generator, or validated
anatomical measurement model. Canonical units are not millimeters.

Asset and license SHA-256 values, the source URLs and transformation are stored
in data/base-face/base-face.json and copied to exported bundle manifests.

React, Vite, Three.js, Lucide, FastAPI, Uvicorn, Pillow and other dependencies
retain their own licenses in their installed distributions. Their exact
versions are recorded in frontend/package-lock.json and requirements-lock.txt.

## FLAME 2023 Open

The local model is downloaded separately from the official FLAME 2023 Open endpoint:
https://download.is.tue.mpg.de/download.php?domain=flame&sfile=FLAME2023Open.zip

Attribution: Tianye Li, Timo Bolkart, Michael J. Black, Hao Li, Javier Romero,
Learning a model of facial shape and expression from 4D scans,
ACM Transactions on Graphics / SIGGRAPH Asia 2017, 36(6), 194:1–194:17.
Model ownership: Max Planck Institute for Intelligent Systems / Max Planck Society.

The official FLAME 2023 Open model is identified as CC-BY-4.0 on its model page.
The official terms and scope are in the **Open Model License** section at
https://flame.is.tue.mpg.de/modellicense.html (the same page also contains the
different academic license for older models).
This applies specifically to Open; old FLAME versions, textures and third-party
reconstruction networks have separate terms.

This project converts numeric arrays into a local internal representation,
normalizes coordinates and applies a reviewed, local nasal-ala deformation.
Original model files and blendshape bases are excluded from source control and
reference ZIP exports. Export manifests contain model/source hashes, attribution,
license links and the calibration version. No texture maps are included.
