{ lib, stdenv, fetchurl, autoPatchelfHook, autoAddDriverRunpath, cudaPackages_12_8, openssl }:

# Install the server and its dynamically discovered CPU/CUDA backends together.
stdenv.mkDerivation rec {
  pname = "inkling-llama-server";
  version = "b12651";
  src = fetchurl {
    url = "https://github.com/ggml-org/llama.cpp/releases/download/${version}/llama-${version}-bin-ubuntu-cuda-12.8-x64.tar.gz";
    hash = "sha256-ywmTUMagJeZ+76oT8rZ7LczlPjig2iJHbgcNFm7zZ+o=";
  };
  nativeBuildInputs = [ autoPatchelfHook autoAddDriverRunpath ];
  buildInputs = [ stdenv.cc.cc.lib openssl cudaPackages_12_8.cuda_cudart cudaPackages_12_8.libcublas ];
  autoPatchelfIgnoreMissingDeps = [ "libcuda.so.1" ];
  dontConfigure = true;
  dontBuild = true;
  installPhase = ''
    mkdir -p "$out/bin" "$out/libexec/llama" "$out/share/licenses/$pname"
    cp -a llama-server libllama-server-impl.so libllama-common.so* libllama.so* libmtmd.so* \
      libggml.so* libggml-base.so* libggml-cpu-*.so libggml-cuda.so "$out/libexec/llama/"
    ln -s ../libexec/llama/llama-server "$out/bin/llama-server"
    cp LICENSE "$out/share/licenses/$pname/"
  '';
  prependRunpaths = [ "$out/libexec/llama" ];
  meta = {
    description = "Pinned CUDA 12.8 llama.cpp server for Inkling 2 Mini";
    license = lib.licenses.mit;
    platforms = [ "x86_64-linux" ];
    mainProgram = "llama-server";
  };
}
