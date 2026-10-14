// How the browser tests draw WebGL. Default: SwiftShader (software on the CPU), the same pixels on every machine.
// VIZ_GPU=1: the machine's GPU through ANGLE/Vulkan — much lighter on the CPU for behaviour tests. Pixel comparisons
// (scripts/shotset.mjs, the field guide recording) always use SwiftShader.
// `npm run test:gpu [-- test/<file>]` runs the tests this way, one file at a time (VIZ_CHROMIUM defaults to /usr/bin/chromium).
export const GL_ARGS: string[] = process.env.VIZ_GPU === "1"
  ? ["--use-angle=vulkan", "--enable-features=Vulkan", "--ignore-gpu-blocklist"]
  : ["--use-gl=swiftshader", "--enable-unsafe-swiftshader"];
