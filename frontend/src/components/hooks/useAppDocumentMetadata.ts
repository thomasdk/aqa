import { useEffect } from "react";
import type { TFunction } from "i18next";
import { localeTag } from "../../i18n";

export function useAppDocumentMetadata(resolvedLanguage: string | undefined, t: TFunction): void {
  useEffect(() => {
    document.documentElement.lang = localeTag(resolvedLanguage);
    document.title = t("app.title");
  }, [resolvedLanguage, t]);
}
