"use strict";
(() => {
  let connection = null;
  let quitting = false;
  function connect() {
    if (!quitting && !connection) connection = new EventSource('/api/page-session');
  }
  function disconnect() {
    if (connection) connection.close();
    connection = null;
  }
  window.GeoPortPage = {
    exited() {
      quitting = true;
      disconnect();
      window.close();
    }
  };
  window.addEventListener('pagehide', disconnect);
  window.addEventListener('pageshow', connect);
  connect();
})();
