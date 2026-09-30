import { useEffect } from "react";
import Layout from "./components/Layout";
import {
  initializeRoundNotifications,
  requestInitialDesktopNotificationPermission,
} from "./roundNotifications";
import { persistNotificationPermissionAutoAttempt } from "./uiPreferences";

const App = ({
  notificationPermissionAutoAttempted,
}: {
  notificationPermissionAutoAttempted: boolean | null;
}) => {
  useEffect(() => {
    void initializeRoundNotifications().then(() =>
      requestInitialDesktopNotificationPermission(
        notificationPermissionAutoAttempted,
        persistNotificationPermissionAutoAttempt,
      ),
    );
  }, [notificationPermissionAutoAttempted]);
  return <Layout />;
};

export default App;
