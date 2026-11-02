const adminDatabase = db.getSiblingDB("admin");
const replicaStatus = adminDatabase.runCommand({ replSetGetStatus: 1 });

if (replicaStatus.ok !== 1) {
  const initiation = adminDatabase.runCommand({
    replSetInitiate: {
      _id: "rs0",
      members: [{ _id: 0, host: "mongodb:27017" }],
    },
  });
  if (initiation.ok !== 1 && initiation.codeName !== "AlreadyInitialized") {
    throw new Error(`MongoDB replica set initialization failed: ${initiation.codeName}`);
  }
}

let isPrimary = false;
for (let attempt = 0; attempt < 60; attempt += 1) {
  const hello = adminDatabase.runCommand({ hello: 1 });
  if (hello.isWritablePrimary) {
    isPrimary = true;
    break;
  }
  sleep(1000);
}
if (!isPrimary) {
  throw new Error("MongoDB did not elect a primary within 60 seconds.");
}

const applicationDatabase = db.getSiblingDB(process.env.MONGO_DATABASE);
const applicationUser = process.env.MONGO_APP_USERNAME;
const applicationPassword = process.env.MONGO_APP_PASSWORD;
if (!applicationUser || !applicationPassword) {
  throw new Error("MongoDB application credentials are required.");
}

if (applicationDatabase.getUser(applicationUser)) {
  applicationDatabase.updateUser(applicationUser, {
    pwd: applicationPassword,
    roles: [{ role: "readWrite", db: process.env.MONGO_DATABASE }],
  });
} else {
  applicationDatabase.createUser({
    user: applicationUser,
    pwd: applicationPassword,
    roles: [{ role: "readWrite", db: process.env.MONGO_DATABASE }],
  });
}
