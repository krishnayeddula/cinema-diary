/// <reference path="../pb_data/types.d.ts" />
// Invite-only: only superusers create or delete accounts.
// A user can see and update only their own record.
migrate((app) => {
  const users = app.findCollectionByNameOrId("users");
  const self = '@request.auth.id != "" && id = @request.auth.id';
  users.listRule = self;
  users.viewRule = self;
  users.createRule = null;
  users.updateRule = self;
  users.deleteRule = null;
  app.save(users);
}, (app) => {
  const users = app.findCollectionByNameOrId("users");
  users.listRule = "id = @request.auth.id";
  users.viewRule = "id = @request.auth.id";
  users.createRule = "";
  users.updateRule = "id = @request.auth.id";
  users.deleteRule = "id = @request.auth.id";
  app.save(users);
});
