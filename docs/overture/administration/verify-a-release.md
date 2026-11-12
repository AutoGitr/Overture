---
sidebar_position: 3
title: Verify a release
description: Check the Sigstore signature of an image or archive before running it.
---

# Verify a release

Each release is signed by its GitHub workflow with Sigstore. Check an image
with [cosign](https://docs.sigstore.dev/cosign/system_config/installation/)
3.1 or newer before you run it, and the native archive before you install it:

```sh
IDENTITY='^https://github.com/AutoGitr/Overture/\.github/workflows/release\.yml@refs/(tags/v.+|heads/main)$'
ISSUER=https://token.actions.githubusercontent.com

# GHCR keeps the signatures in a package of their own.
COSIGN_REPOSITORY=ghcr.io/autogitr/overture-signatures cosign verify \
  ghcr.io/autogitr/overture:<version> \
  --certificate-identity-regexp "$IDENTITY" --certificate-oidc-issuer "$ISSUER"
cosign verify docker.io/autogitr/overture:<version> \
  --certificate-identity-regexp "$IDENTITY" --certificate-oidc-issuer "$ISSUER"

cosign verify-blob overture-<version>-linux-x86_64.tar.gz \
  --bundle overture-<version>-linux-x86_64.tar.gz.sigstore.json \
  --certificate-identity-regexp "$IDENTITY" --certificate-oidc-issuer "$ISSUER"

# Every file attached to the release
gh release verify v<version> --repo AutoGitr/Overture
```

The release notes list the image digest. The image carries its SPDX SBOM and
build provenance, and the SBOMs are also attached to the release.
