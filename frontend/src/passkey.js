const toBuffer = (value) => {
  const text = String(value || "").replace(/-/g, "+").replace(/_/g, "/");
  const padded = text + "=".repeat((4 - (text.length % 4)) % 4);
  const binary = atob(padded);
  const bytes = new Uint8Array(binary.length);
  for (let index = 0; index < binary.length; index += 1) bytes[index] = binary.charCodeAt(index);
  return bytes.buffer;
};

const fromBuffer = (value) => {
  const bytes = new Uint8Array(value);
  let binary = "";
  bytes.forEach((item) => { binary += String.fromCharCode(item); });
  return btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/g, "");
};

export const passkeySupported = () => typeof window !== "undefined" && typeof window.PublicKeyCredential !== "undefined";

export const creationOptions = (options) => ({
  ...options,
  challenge: toBuffer(options.challenge),
  user: { ...options.user, id: toBuffer(options.user.id) },
  excludeCredentials: (options.excludeCredentials || []).map((item) => ({ ...item, id: toBuffer(item.id) })),
});

export const requestOptions = (options) => ({
  ...options,
  challenge: toBuffer(options.challenge),
  allowCredentials: (options.allowCredentials || []).map((item) => ({ ...item, id: toBuffer(item.id) })),
});

export const credentialToJSON = (credential) => {
  const response = credential.response;
  const body = {
    id: credential.id,
    rawId: credential.id,
    type: credential.type,
    clientExtensionResults: credential.getClientExtensionResults ? credential.getClientExtensionResults() : {},
    response: {
      clientDataJSON: fromBuffer(response.clientDataJSON),
    },
  };
  if (response.attestationObject) {
    body.response.attestationObject = fromBuffer(response.attestationObject);
    if (response.getTransports) body.response.transports = response.getTransports();
  } else {
    body.response.authenticatorData = fromBuffer(response.authenticatorData);
    body.response.signature = fromBuffer(response.signature);
    if (response.userHandle) body.response.userHandle = fromBuffer(response.userHandle);
  }
  return body;
};
