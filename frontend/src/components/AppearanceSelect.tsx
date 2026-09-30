import { useTranslation } from "react-i18next";
import { isAppearance, useAppearance } from "../appearance";
import { selectPersistedAppearance } from "../uiPreferences";
import { Field, Select } from "./design-system";

export function AppearanceSelect() {
  const { t } = useTranslation();
  const appearance = useAppearance();
  return (
    <Field label={t("system.appearanceMode")} description={t("system.appearanceHelp")}>
      <Select
        value={appearance}
        onChange={(event) => {
          if (isAppearance(event.target.value)) void selectPersistedAppearance(event.target.value);
        }}
      >
        <option value="system">{t("system.appearanceSystem")}</option>
        <option value="light">{t("system.appearanceLight")}</option>
        <option value="dark">{t("system.appearanceDark")}</option>
      </Select>
    </Field>
  );
}
