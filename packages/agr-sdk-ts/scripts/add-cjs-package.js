// Post-build: mark dist/cjs/ as CommonJS so Node resolves .js files correctly
const fs = require("fs");
fs.writeFileSync("dist/cjs/package.json", JSON.stringify({ type: "commonjs" }));
