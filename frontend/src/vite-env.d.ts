/// <reference types="vite/client" />

declare module "*.html?raw" {
  const template: string;
  export default template;
}
