import type { ConditionInput, FilterGroupInput, MediaType } from "../../generated/rest/types.gen";

/** A copied condition or group, and the media type whose fields it names. */
type Copied = { mediaType: MediaType } & (
  { kind: "condition"; condition: ConditionInput } | { kind: "group"; group: FilterGroupInput }
);

/** Criteria copied from one collection to paste into another. */
class CriteriaClipboard {
  copied = $state.raw<Copied | null>(null);

  copyCondition(mediaType: MediaType, condition: ConditionInput) {
    this.copied = { mediaType, kind: "condition", condition: $state.snapshot(condition) };
  }

  copyGroup(mediaType: MediaType, group: FilterGroupInput) {
    this.copied = { mediaType, kind: "group", group: $state.snapshot(group) };
  }

  /** What can be pasted into criteria for *mediaType*: fields differ between movies and shows. */
  pasteable(mediaType: MediaType): Copied | null {
    return this.copied?.mediaType === mediaType ? this.copied : null;
  }
}

export const criteriaClipboard = new CriteriaClipboard();
