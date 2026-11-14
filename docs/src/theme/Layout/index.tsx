import Head from "@docusaurus/Head";
import type { WrapperProps } from "@docusaurus/types";
import useBaseUrl from "@docusaurus/useBaseUrl";
import Layout from "@theme-original/Layout";
import type LayoutType from "@theme/Layout";
import type { ReactNode } from "react";
import { useBrand } from "../../brand";

/** Every page, with the tab icon of the project it documents. */
export default function LayoutWrapper(props: WrapperProps<typeof LayoutType>): ReactNode {
  const icon = useBaseUrl(`${useBrand()}-tab.svg`);
  return (
    <>
      <Head>
        <link rel="icon" href={icon} />
      </Head>
      <Layout {...props} />
    </>
  );
}
