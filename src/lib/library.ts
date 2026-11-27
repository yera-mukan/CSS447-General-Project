import { apiBase, remote } from "./api"
import { local } from "./local"
export const library = apiBase ? remote : local
