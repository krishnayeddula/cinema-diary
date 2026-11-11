/// <reference path="../pb_data/types.d.ts" />
// P2: private per-user diary collections.
// Every row belongs to one user. Only that user can see, create, change or
// delete it. The import service account cannot read any of it.
migrate((app) => {
  const users  = app.findCollectionByNameOrId("users");
  const movies = app.findCollectionByNameOrId("movies");
  const people = app.findCollectionByNameOrId("people");

  const IS_USER = '@request.auth.id != "" && @request.auth.collectionName = "users"';
  const OWNER   = IS_USER + " && user = @request.auth.id";
  const rules = {
    listRule:   OWNER,
    viewRule:   OWNER,
    // you can only create rows for yourself
    createRule: IS_USER + " && @request.body.user = @request.auth.id",
    // you can't hand a row over to someone else
    updateRule: OWNER + " && (@request.body.user:isset = false || @request.body.user = @request.auth.id)",
    deleteRule: OWNER,
  };

  const owner = { type: "relation", name: "user", required: true, maxSelect: 1,
                  collectionId: users.id, cascadeDelete: true };
  const movie = { type: "relation", name: "movie", required: true, maxSelect: 1,
                  collectionId: movies.id, cascadeDelete: false };
  const stamps = [
    { type: "autodate", name: "created", onCreate: true, onUpdate: false },
    { type: "autodate", name: "updated", onCreate: true, onUpdate: true },
  ];
  const company = ["alone", "partner", "family", "friends", "kids"];
  const aspect = (name) => ({ type: "number", name, onlyInt: true, min: 1, max: 5 });

  app.save(new Collection({
    type: "base", name: "taste_profile", ...rules,
    fields: [
      owner,
      { type: "json", name: "languages" },   // ["te", "ta", "bn"]
      { type: "json", name: "genres" },      // ["Drama", "Romance"]
      { type: "json", name: "eras" },        // ["1970s", "1980s"]
      ...stamps,
    ],
    indexes: ["CREATE UNIQUE INDEX idx_taste_profile_user ON taste_profile (user)"],
  }));

  app.save(new Collection({
    type: "base", name: "favorites", ...rules,
    fields: [
      owner,
      { type: "relation", name: "person", required: true, maxSelect: 1,
        collectionId: people.id, cascadeDelete: false },
      { type: "select", name: "role", required: true, maxSelect: 1,
        values: ["director", "actor", "composer", "lyricist", "writer", "cinematographer"] },
      ...stamps,
    ],
    indexes: ["CREATE UNIQUE INDEX idx_favorites_unique ON favorites (user, person, role)"],
  }));

  app.save(new Collection({
    type: "base", name: "watches", ...rules,
    fields: [
      owner,
      movie,
      { type: "date", name: "watched_on", required: true },
      { type: "select", name: "watched_with", maxSelect: 1, values: company },
      ...stamps,
    ],
    indexes: ["CREATE INDEX idx_watches_user_date ON watches (user, watched_on)"],
  }));

  app.save(new Collection({
    type: "base", name: "reviews", ...rules,
    fields: [
      owner,
      movie,
      { type: "number", name: "stars", required: true, onlyInt: true, min: 1, max: 5 },
      aspect("story"), aspect("acting"), aspect("music"),
      aspect("direction"), aspect("visuals"), aspect("pace"),
      { type: "select", name: "emotions", maxSelect: 10,
        values: ["moved", "joyful", "thrilled", "tense", "nostalgic",
                 "inspired", "sad", "amused", "disturbed", "bored"] },
      { type: "bool", name: "would_rewatch" },
      { type: "bool", name: "would_recommend" },
      { type: "select", name: "best_with", maxSelect: 1, values: company },
      { type: "text", name: "note", max: 280 },
      ...stamps,
    ],
    indexes: ["CREATE UNIQUE INDEX idx_reviews_user_movie ON reviews (user, movie)"],
  }));

  app.save(new Collection({
    type: "base", name: "watchlist", ...rules,
    fields: [owner, movie, ...stamps],
    indexes: ["CREATE UNIQUE INDEX idx_watchlist_user_movie ON watchlist (user, movie)"],
  }));
}, (app) => {
  for (const name of ["watchlist", "reviews", "watches", "favorites", "taste_profile"]) {
    app.delete(app.findCollectionByNameOrId(name));
  }
});
