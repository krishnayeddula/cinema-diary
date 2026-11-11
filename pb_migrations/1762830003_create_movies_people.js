/// <reference path="../pb_data/types.d.ts" />
// TMDB-sourced catalog. Record ids are derived from tmdb ids by the worker
// (sha256 -> first 15 hex chars), so re-running an import updates instead of duplicating.
migrate((app) => {
  const READ  = '@request.auth.id != ""';
  const WRITE = '@request.auth.id != "" && @request.auth.collectionName = "service_accounts"';
  const stamps = [
    { type: "autodate", name: "created", onCreate: true, onUpdate: false },
    { type: "autodate", name: "updated", onCreate: true, onUpdate: true },
  ];

  const movies = new Collection({
    type: "base",
    name: "movies",
    listRule: READ, viewRule: READ,
    createRule: WRITE, updateRule: WRITE, deleteRule: null,
    fields: [
      { type: "number", name: "tmdb_id", required: true, onlyInt: true },
      { type: "text",   name: "title", required: true },
      { type: "text",   name: "original_title" },
      { type: "text",   name: "original_language" },
      { type: "text",   name: "release_date" },
      { type: "number", name: "year", onlyInt: true },
      { type: "number", name: "runtime", onlyInt: true },
      { type: "json",   name: "genres" },
      { type: "text",   name: "overview" },
      { type: "text",   name: "poster_path" },
      { type: "date",   name: "tmdb_synced_at" },
      ...stamps,
    ],
    indexes: ["CREATE UNIQUE INDEX idx_movies_tmdb_id ON movies (tmdb_id)"],
  });
  app.save(movies);

  const people = new Collection({
    type: "base",
    name: "people",
    listRule: READ, viewRule: READ,
    createRule: WRITE, updateRule: WRITE, deleteRule: null,
    fields: [
      { type: "number", name: "tmdb_id", required: true, onlyInt: true },
      { type: "text",   name: "name", required: true },
      { type: "text",   name: "known_for_department" },
      { type: "text",   name: "profile_path" },
      { type: "date",   name: "tmdb_synced_at" },
      ...stamps,
    ],
    indexes: ["CREATE UNIQUE INDEX idx_people_tmdb_id ON people (tmdb_id)"],
  });
  app.save(people);
}, (app) => {
  app.delete(app.findCollectionByNameOrId("people"));
  app.delete(app.findCollectionByNameOrId("movies"));
});
