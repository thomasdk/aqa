/**
 * Prompt configuration is user-authored domain content, not UI copy. The
 * client deliberately renders it exactly as supplied by the API.
 */
export function sessionInputText(value: string | null | undefined): string {
  return value ?? "";
}
