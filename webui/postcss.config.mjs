import { fileURLToPath } from "node:url";

import postcssGlobalData from "@csstools/postcss-global-data";
import postcssCustomMedia from "postcss-custom-media";

const responsiveMediaPath = fileURLToPath(
  new URL("./src/assets/styles/responsive.css", import.meta.url),
);

export default {
  plugins: [
    postcssGlobalData({
      files: [responsiveMediaPath],
    }),
    postcssCustomMedia(),
  ],
};
