import { useCallback, useEffect, useRef, type ReactElement } from "react";
import { useTranslation } from "react-i18next";

const AQA_BRAND_LABEL_ID = "aqa-brand-label";
const GENERATING_PLAYBACK_RATE = 3.9 / 0.8;

type NamedAnimation = Animation & { animationName?: string };

const updateWavePlaybackRate = (root: HTMLElement, playbackRate: number): void => {
  root.querySelectorAll<Element>("[data-aqa-wave]").forEach((participant) => {
    if (typeof participant.getAnimations !== "function") return;
    participant.getAnimations().forEach((animation: NamedAnimation) => {
      if (animation.animationName === "aqa-brand-wave") {
        // Unlike changing animation-duration, updatePlaybackRate preserves the
        // current timeline position while generation changes the wave speed.
        animation.updatePlaybackRate(playbackRate);
      }
    });
  });
};

/**
 * Duplicated from `aqa-logo.svg` so the animated drops remain inline SVGs;
 * the Material Symbols font is reserved for application icons.
 */
const DROP_PATHS = {
  outline:
    "M480,-100C391.333,-100 315.833,-130.667 253.5,-192C191.167,-253.333 160,-328 160,-416C160,-458 168.167,-498.167 184.5,-536.5C200.833,-574.833 224,-608.667 254,-638L480,-860L706,-638C736,-608.667 759.167,-574.833 775.5,-536.5C791.833,-498.167 800,-458 800,-416C800,-328 768.833,-253.333 706.5,-192C644.167,-130.667 568.667,-100 480,-100ZM650,-248.5C696.667,-294.167 720,-350 720,-416C720,-447.333 714,-477.167 702,-505.5C690,-533.833 672.667,-558.667 650,-580L480,-748L310,-580C287.333,-558.667 270,-533.833 258,-505.5C246,-477.167 240,-447.333 240,-416C240,-350 263.333,-294.167 310,-248.5C356.667,-202.833 413.333,-180 480,-180C546.667,-180 603.333,-202.833 650,-248.5Z",
  half: "M480,-100C391.333,-100 315.833,-130.667 253.5,-192C191.167,-253.333 160,-328 160,-416C160,-458 168.167,-498.167 184.5,-536.5C200.833,-574.833 224,-608.667 254,-638L480,-860L706,-638C736,-608.667 759.167,-574.833 775.5,-536.5C791.833,-498.167 800,-458 800,-416C800,-328 768.833,-253.333 706.5,-192C644.167,-130.667 568.667,-100 480,-100ZM240,-416L720,-416C720,-447.333 714,-477.167 702,-505.5C690,-533.833 672.667,-558.667 650,-580L480,-748L310,-580C287.333,-558.667 270,-533.833 258,-505.5C246,-477.167 240,-447.333 240,-416Z",
  full: "M480,-100C391.333,-100 315.833,-130.667 253.5,-192C191.167,-253.333 160,-328 160,-416C160,-458 168.167,-498.167 184.5,-536.5C200.833,-574.833 224,-608.667 254,-638L480,-860L706,-638C736,-608.667 759.167,-574.833 775.5,-536.5C791.833,-498.167 800,-458 800,-416C800,-328 768.833,-253.333 706.5,-192C644.167,-130.667 568.667,-100 480,-100Z",
} as const;

type DropFill = keyof typeof DROP_PATHS;
type DropSide = "left" | "right";
type WaveOrdinal = 1 | 2 | 3 | 4 | 5 | 6 | 7;

interface DropSpec {
  slot: string;
  side: DropSide;
  fill: DropFill;
  wave: WaveOrdinal;
}

const LEFT_DROPS: ReadonlyArray<DropSpec> = [
  { slot: "left-outline", side: "left", fill: "outline", wave: 1 },
  { slot: "left-half", side: "left", fill: "half", wave: 2 },
];

const RIGHT_DROPS: ReadonlyArray<DropSpec> = [
  { slot: "right-half", side: "right", fill: "half", wave: 6 },
  { slot: "right-full", side: "right", fill: "full", wave: 7 },
];

const Drop = ({ spec }: { spec: DropSpec }): ReactElement => {
  const { slot, side, fill, wave } = spec;
  return (
    <svg
      className={`aqa-drop aqa-drop-${fill}`}
      data-aqa-drop={slot}
      data-aqa-side={side}
      data-aqa-fill={fill}
      data-aqa-wave={wave}
      viewBox="0 0 960 960"
      aria-hidden="true"
      focusable="false"
    >
      <path d={DROP_PATHS[fill]} transform="translate(0 960)" />
    </svg>
  );
};

/**
 * The visual mark is decorative and receives one independent accessible name.
 * With `onActivate`, the root becomes a keyboard-accessible return control.
 */
const AqaBrand = ({
  isGenerating = false,
  onActivate,
}: {
  isGenerating?: boolean;
  onActivate?: () => void;
}): ReactElement => {
  const { t } = useTranslation();
  const brandRef = useRef<HTMLElement | null>(null);
  const setBrandRef = useCallback((element: HTMLElement | null) => {
    brandRef.current = element;
  }, []);

  useEffect(() => {
    if (brandRef.current) {
      updateWavePlaybackRate(brandRef.current, isGenerating ? GENERATING_PLAYBACK_RATE : 1);
    }
  }, [isGenerating]);

  const contents = (
    <>
      <div className="aqa-brand-lockup" aria-hidden="true">
        {LEFT_DROPS.map((spec) => (
          <Drop key={spec.slot} spec={spec} />
        ))}
      </div>
      <span className="aqa-brand-wordmark" aria-hidden="true">
        <span className="aqa-brand-letter" data-aqa-wave="3" aria-hidden="true">
          A
        </span>
        <span className="aqa-brand-letter" data-aqa-wave="4" aria-hidden="true">
          Q
        </span>
        <span className="aqa-brand-letter" data-aqa-wave="5" aria-hidden="true">
          A
        </span>
      </span>
      <div className="aqa-brand-lockup" aria-hidden="true">
        {RIGHT_DROPS.map((spec) => (
          <Drop key={spec.slot} spec={spec} />
        ))}
      </div>
      <span id={AQA_BRAND_LABEL_ID} className="visually-hidden">
        AQA
      </span>
      <span className="aqa-brand-tagline">{t("app.tagline")}</span>
    </>
  );
  const commonProps = {
    ref: setBrandRef,
    className: "aqa-brand",
    "data-aqa-brand": "true",
    "data-aqa-generating": isGenerating ? "true" : "false",
    "aria-labelledby": AQA_BRAND_LABEL_ID,
  };

  if (onActivate) {
    return (
      <button type="button" {...commonProps} onClick={onActivate}>
        {contents}
      </button>
    );
  }

  return <div {...commonProps}>{contents}</div>;
};

export default AqaBrand;
