/// <reference path="../pb_data/types.d.ts" />
// Machine identities (the TMDB import worker). Managed by superusers only.
migrate((app) => {
  const c = new Collection({
    type: "auth",
    name: "service_accounts",
    listRule: null,
    viewRule: null,
    createRule: null,
    updateRule: null,
    deleteRule: null,
  });
  app.save(c);
}, (app) => {
  app.delete(app.findCollectionByNameOrId("service_accounts"));
});
