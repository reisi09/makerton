// GitHub Pages(https://reisi09.github.io/makerton/)에 정적 파일로 올린다.
const basePath = process.env.BASE_PATH ?? "/makerton";

/** @type {import('next').NextConfig} */
export default {
  output: "export",
  basePath,
  trailingSlash: true,
  images: { unoptimized: true },
  env: { NEXT_PUBLIC_BASE_PATH: basePath },
};
