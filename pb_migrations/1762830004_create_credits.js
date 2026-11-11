/// <reference path="../pb_data/types.d.ts" />
// One row per TMDB credit. TMDB's credit_id is unique, so it drives the derived record id.
migrate((app) => {
  const READ  = '@request.auth.id != ""';
  const WRITE = '@request.auth.id != "" && @request.auth.collectionName = "service_accounts"';
  const movies = app.findCollectionByNameOrId("movies");
  const people = app.findCollectionByNameOrId("people");

  const credits = new Collection({
    type: "base",
    name: "credits",
    listRule: READ, viewRule: READ,
    createRule: WRITE, updateRule: WRITE, deleteRule: null,
    fields: [
      { type: "text",     name: "tmdb_credit_id", required: true },
      { type: "relation", name: "movie",  required: true, maxSelect: 1, collectionId: movies.id, cascadeDelete: true },
      { type: "relation", name: "person", required: true, maxSelect: 1, collectionId: people.id, cascadeDelete: true },
      { type: "select",   name: "kind", required: true, maxSelect: 1, values: ["cast", "crew"] },
      { type: "text",     name: "character" },
      { type: "text",     name: "job" },
      { type: "text",     name: "department" },
      { type: "number",   name: "order", onlyInt: true },
      { type: "autodate", name: "created", onCreate: true, onUpdate: false },
      { type: "autodate", name: "updated", onCreate: true, onUpdate: true },
    ],
    indexes: [
      "CREATE UNIQUE INDEX idx_credits_tmdb_credit_id ON credits (tmdb_credit_id)",
      "CREATE INDEX idx_credits_person ON credits (person)",
    ],
  });
  app.save(credits);
}, (app) => {
  app.delete(app.findCollectionByNameOrId("credits"));
});
