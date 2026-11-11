/// <reference path="../pb_data/types.d.ts" />
// P2: a user's curated list ("films that match my stated taste").
// Written by the curate job running AS THAT USER, so the same owner-only
// rules apply as for the rest of the diary.
migrate((app) => {
  const users  = app.findCollectionByNameOrId("users");
  const movies = app.findCollectionByNameOrId("movies");

  const IS_USER = '@request.auth.id != "" && @request.auth.collectionName = "users"';
  const OWNER   = IS_USER + " && user = @request.auth.id";

  app.save(new Collection({
    type: "base",
    name: "curated_items",
    listRule:   OWNER,
    viewRule:   OWNER,
    createRule: IS_USER + " && @request.body.user = @request.auth.id",
    updateRule: OWNER + " && (@request.body.user:isset = false || @request.body.user = @request.auth.id)",
    deleteRule: OWNER,
    fields: [
      { type: "relation", name: "user", required: true, maxSelect: 1,
        collectionId: users.id, cascadeDelete: true },
      { type: "relation", name: "movie", required: true, maxSelect: 1,
        collectionId: movies.id, cascadeDelete: true },
      { type: "number", name: "rank", required: true, onlyInt: true, min: 1 },
      { type: "number", name: "score", required: true, min: 0 },
      { type: "json",   name: "reasons" },   // ["Directed by Satyajit Ray", "Bengali", "1960s"]
      { type: "autodate", name: "created", onCreate: true, onUpdate: false },
      { type: "autodate", name: "updated", onCreate: true, onUpdate: true },
    ],
    indexes: ["CREATE UNIQUE INDEX idx_curated_user_movie ON curated_items (user, movie)"],
  }));
}, (app) => {
  app.delete(app.findCollectionByNameOrId("curated_items"));
});
