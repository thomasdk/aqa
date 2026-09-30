/** Generation ids prevent late callbacks from overwriting a newer discussion. */

export type DiscussionGeneration = {
  id: number;
};

export const INITIAL_DISCUSSION_GENERATION: DiscussionGeneration = { id: 0 };

export function beginDiscussionGeneration(previous: DiscussionGeneration): DiscussionGeneration {
  return { id: previous.id + 1 };
}

export function invalidateDiscussionGeneration(
  previous: DiscussionGeneration,
): DiscussionGeneration {
  return beginDiscussionGeneration(previous);
}

export function isCurrentDiscussionGeneration(
  current: DiscussionGeneration,
  candidateId: number,
): boolean {
  return current.id === candidateId;
}
