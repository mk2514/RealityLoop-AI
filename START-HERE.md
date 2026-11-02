# Run RealityLoop AI locally
Extract the ZIP first. Open a terminal in the folder containing this file.
With Python 3 installed, run:
```sh
python -m http.server 8000 --bind 127.0.0.1 --directory dist
```
On Windows, use py instead of python if needed. Open http://localhost:8000 in your browser. Press Ctrl+C to stop.
All application code and Three.js dependencies are included. No npm install, API keys or cloud account required. The 3D view needs WebGL. Open the site through localhost rather than double-clicking index.html.
Upload the extracted files and folders to GitHub to track the editable project. The static web root is dist/.
