import Link from "@docusaurus/Link";
import useBaseUrl from "@docusaurus/useBaseUrl";
import ThemedImage from "@theme/ThemedImage";
import type { ReactNode } from "react";
import { BRANDS, useBrand } from "../../../brand";

/** The logo of the project whose pages are open, linking to its home page. */
export default function NavbarLogo(): ReactNode {
  const brand = useBrand();
  const { name, home, logoWidth } = BRANDS[brand];
  const sources = {
    light: useBaseUrl(`${brand}-logo-inline-light.svg`),
    dark: useBaseUrl(`${brand}-logo-inline-dark.svg`),
  };
  return (
    <Link to={home} className="navbar__brand">
      <ThemedImage
        className="navbar__logo"
        alt={name}
        sources={sources}
        width={logoWidth}
        height={32}
      />
    </Link>
  );
}
