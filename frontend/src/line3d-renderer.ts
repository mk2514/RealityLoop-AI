import * as THREE from "three";

export function createReviewRenderer(): THREE.WebGLRenderer {
  return new THREE.WebGLRenderer({ antialias: true, alpha: false });
}
