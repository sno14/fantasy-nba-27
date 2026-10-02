import { readFileSync } from "node:fs";
import { validateMinutesArtifact } from "../static/minutes.mjs";

const board = JSON.parse(readFileSync(new URL("../static/data/board.json", import.meta.url), "utf8"));
const minutes = JSON.parse(readFileSync(new URL("../static/data/minutes.json", import.meta.url), "utf8"));
const allowed = ["board_rows", "generated_at", "max_mpg", "min_mpg", "rows", "schema", "scoring_key", "season", "step_mpg"];
if (Object.keys(minutes).sort().join() !== allowed.join()) throw new Error("Unexpected public minutes fields.");
validateMinutesArtifact(minutes, board);
if (!Object.keys(minutes.rows).length) throw new Error("No verified public minutes curves.");
console.log(`Validated ${Object.keys(minutes.rows).length} public minutes curves for ${board.generated_at}`);
