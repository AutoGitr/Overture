import type { ConditionInput, FilterGroupInput, MediaType } from "../../generated/rest/types.gen";
import { conditionFits, groupFits, type CriteriaTarget } from "../utils/collectionCriteria";

/** A copied condition or group, and the media type whose fields it names. */
type Copied = { mediaType: MediaType } & (
  { kind: "condition"; condition: ConditionInput } | { kind: "group"; group: FilterGroupInput }
);

/** Criteria copied from one collection, set or library to paste into another. */
class CriteriaClipboard {
  copied = $state.raw<Copied | null>(null);

  copyCondition(mediaType: MediaType, condition: ConditionInput) {
    this.copied = { mediaType, kind: "condition", condition: $state.snapshot(condition) };
  }

  copyGroup(mediaType: MediaType, group: FilterGroupInput) {
    this.copied = { mediaType, kind: "group", group: $state.snapshot(group) };
  }

  /** Whether criteria offering *target* can test everything copied. */
  fits(target: CriteriaTarget): boolean {
    const copied = this.copied;
    if (!copied) return false;
    return copied.kind === "condition"
      ? conditionFits(copied.condition, target, copied.mediaType)
      : groupFits(copied.group, target, copied.mediaType);
  }
}

export const criteriaClipboard = new CriteriaClipboard();
