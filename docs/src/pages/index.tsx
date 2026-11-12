import Link from "@docusaurus/Link";
import useBaseUrl from "@docusaurus/useBaseUrl";
import { useColorMode } from "@docusaurus/theme-common";
import Layout from "@theme/Layout";
import type { ReactNode } from "react";

import styles from "./index.module.css";

const cards = [
  {
    title: "Install Overture",
    body: "Docker or a native Linux service, connected to Plex, Jellyfin or Emby in a few steps.",
    to: "/overture/install",
  },
  {
    title: "Artwork and themes",
    body: "Compare candidates, upload your own, preview themes and keep every choice beside your media.",
    to: "/overture/features/artwork",
  },
  {
    title: "Collections",
    body: "Build collections from criteria, franchises and lists, and let scheduled syncs keep them current.",
    to: "/overture/features/collections",
  },
  {
    title: "Contribute to OvertureDB",
    body: "Share the posters, backgrounds and themes you chose, so a title only has to be chosen once.",
    to: "/overturedb/contributing",
  },
];

function Logo(): ReactNode {
  const { colorMode } = useColorMode();
  const src = useBaseUrl(`overture-logo-stacked-${colorMode}.svg`);
  return <img className={styles.logo} src={src} alt="Overture" width={320} height={220} />;
}

export default function Home(): ReactNode {
  return (
    <Layout description="Artwork, collections & themes for Plex, Jellyfin and Emby">
      <header className={styles.hero}>
        <Logo />
        <p className={styles.tagline}>
          Complete control of your media library's look and sound. Choose posters, backgrounds,
          season posters and theme songs yourself, or let OvertureDB's community picks fill them in.
        </p>
        <div className={styles.actions}>
          <Link className="button button--primary button--lg" to="/overture/install">
            Get started
          </Link>
          <Link className="button button--secondary button--lg" to="/overture">
            Read the docs
          </Link>
        </div>
      </header>
      <main className={styles.cards}>
        {cards.map((card) => (
          <Link key={card.to} className={styles.card} to={card.to}>
            <h2>{card.title}</h2>
            <p>{card.body}</p>
          </Link>
        ))}
      </main>
    </Layout>
  );
}
