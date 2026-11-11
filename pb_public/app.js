// Cinema Diary front end: plain JS + Alpine.js, talking to PocketBase's REST API
// on the same origin. The auth token lives in localStorage and is sent in the
// Authorization header (never in a URL). PocketBase's API rules decide what
// this user can see; the browser is never trusted with anyone else's data.

const TOKEN_KEY = "cd_token";
const USER_KEY = "cd_user";
const TMDB_IMG = "https://image.tmdb.org/t/p/w185";

function app() {
  return {
    token: localStorage.getItem(TOKEN_KEY) || "",
    user: JSON.parse(localStorage.getItem(USER_KEY) || "null"),
    email: "",
    password: "",
    error: "",
    busy: false,
    picks: [],

    async init() {
      if (this.token) await this.loadList();
    },

    // One place for every API call: adds the token, turns errors into messages.
    async api(path, options = {}) {
      const headers = { "Content-Type": "application/json" };
      if (this.token) headers.Authorization = this.token;
      const res = await fetch(path, { ...options, headers });
      const body = res.status === 204 ? null : await res.json().catch(() => null);
      if (res.status === 401) {
        this.logout();
        throw new Error("Your session expired. Please log in again.");
      }
      if (!res.ok) throw new Error(body?.message || res.statusText);
      return body;
    },

    async login() {
      this.busy = true;
      this.error = "";
      try {
        const data = await this.api("/api/collections/users/auth-with-password", {
          method: "POST",
          body: JSON.stringify({ identity: this.email, password: this.password }),
        });
        this.token = data.token;
        this.user = { id: data.record.id, email: data.record.email };
        localStorage.setItem(TOKEN_KEY, this.token);
        localStorage.setItem(USER_KEY, JSON.stringify(this.user));
        await this.loadList();
      } catch (e) {
        this.error = "Login failed: " + e.message;
      } finally {
        this.password = ""; // don't keep the password around in memory
        this.busy = false;
      }
    },

    logout() {
      this.token = "";
      this.user = null;
      this.picks = [];
      localStorage.removeItem(TOKEN_KEY);
      localStorage.removeItem(USER_KEY);
    },

    async loadList() {
      this.busy = true;
      this.error = "";
      try {
        const q = new URLSearchParams({ sort: "rank", perPage: "50", expand: "movie" });
        const data = await this.api(`/api/collections/curated_items/records?${q}`);
        this.picks = data.items
          .filter((i) => i.expand?.movie)
          .map((i) => ({ ...i, movie: i.expand.movie, reasons: i.reasons || [] }));
      } catch (e) {
        this.error = e.message;
      } finally {
        this.busy = false;
      }
    },

    poster(movie) {
      return movie?.poster_path ? TMDB_IMG + movie.poster_path : "";
    },
  };
}
