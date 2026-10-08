/** The route of a unit's page: `/units/<change>/<n>`, from its name `change/N`. */
export function unitPath(name: string): string {
  return `/units/${name}`;
}
