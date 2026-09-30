CC ?= cc
CFLAGS ?= -std=c11 -Wall -Wextra -Werror -pedantic -O2
NATIVE = ../../native
CASES = ../cases
SOURCES = $(NATIVE)/pokemon.c $(NATIVE)/gen3_rules.c \
	$(NATIVE)/gen3_slice_data.c $(NATIVE)/singles2.c
HEADERS = $(NATIVE)/pokemon.h $(NATIVE)/gen3_rules.h \
	$(NATIVE)/gen3_slice_data.h $(NATIVE)/singles2.h
KERNEL_INCLUDES = $(wildcard $(NATIVE)/pokemon_kernel/*.inc)
CASE_JSON = $(CASES)/regressions/gen3-singles2-complete.json \
	$(CASES)/accepted/decisions-switch-targets.json \
	$(CASES)/derived/accuracy-miss.json \
	$(CASES)/derived/critical-hit.json \
	$(CASES)/derived/priority-extreme-speed.json \
	$(CASES)/derived/grounded-earthquake.json \
	$(CASES)/derived/flying-earthquake-immunity.json \
	$(CASES)/derived/levitate-earthquake-immunity.json \
	$(CASES)/derived/grounded-bone-rush-miss.json \
	$(CASES)/derived/flying-bone-rush-immunity.json \
	$(CASES)/derived/levitate-bone-rush-immunity.json \
	$(CASES)/derived/water-absorb-try-hit.json \
	$(CASES)/derived/water-absorb-heal.json \
	$(CASES)/derived/modify-attack-baseline.json \
	$(CASES)/derived/black-belt-mach-punch.json \
	$(CASES)/derived/burned-non-guts.json \
	$(CASES)/derived/burned-guts.json \
	$(CASES)/derived/burned-guts-black-belt.json \
	$(CASES)/derived/toxic-ramp.json \
	$(CASES)/derived/toxic-switch-reset.json \
	$(CASES)/derived/toxic-switch-in-hazard-order.json \
	$(CASES)/derived/toxic-poison-immunity.json \
	$(CASES)/derived/toxic-steel-immunity.json \
	$(CASES)/derived/sandstorm-lifecycle.json \
	$(CASES)/derived/sandstorm-ground-immunity.json \
	$(CASES)/derived/protect-stall-chain.json \
	$(CASES)/derived/protect-nonstall-reset.json \
	$(CASES)/derived/protect-switch-reset.json \
	$(CASES)/derived/protect-status-accuracy-staging.json \
	$(CASES)/derived/detect-protect-endure-shared-stall-success.json \
	$(CASES)/derived/detect-endure-shared-stall-failure.json \
	$(CASES)/derived/endure-fixed-move-damage.json \
	$(CASES)/derived/endure-multihit-each-hit.json \
	$(CASES)/derived/lock-on-alias-repeat-accuracy.json \
	$(CASES)/derived/lock-on-semi-invulnerable.json \
	$(CASES)/derived/lock-on-protect-and-immunity.json \
	$(CASES)/derived/lock-on-switch-relations.json \
	$(CASES)/derived/wonder-guard-effectiveness.json \
	$(CASES)/derived/wonder-guard-bypass-and-order.json \
	$(CASES)/derived/focus-band-lethal-success.json \
	$(CASES)/derived/focus-band-lethal-failure.json \
	$(CASES)/derived/focus-band-nonlethal-draw.json \
	$(CASES)/derived/leppa-exact-ten-nonfirst.json \
	$(CASES)/derived/leppa-delayed-acquisition-first-zero.json \
	$(CASES)/derived/kings-rock-tackle-success.json \
	$(CASES)/derived/kings-rock-tackle-failure.json \
	$(CASES)/derived/kings-rock-shield-dust.json \
	$(CASES)/derived/kings-rock-arm-thrust-per-hit.json \
	$(CASES)/derived/kings-rock-serene-grace-order.json \
	$(CASES)/derived/shell-bell-single-hit.json \
	$(CASES)/derived/shell-bell-multihit-aggregate.json \
	$(CASES)/derived/shell-bell-overkill-cap.json \
	$(CASES)/derived/shell-bell-substitute-zero.json \
	$(CASES)/derived/fake-out-pressure-ghost-repeat.json \
	$(CASES)/derived/fake-out-flinched-action-counts.json \
	$(CASES)/derived/fake-out-switch-reset.json \
	$(CASES)/derived/happiness-return-default.json \
	$(CASES)/derived/happiness-frustration-import-default.json \
	$(CASES)/derived/happiness-return-zero.json \
	$(CASES)/derived/happiness-frustration-max.json \
	$(CASES)/derived/happiness-return-midpoint.json \
	$(CASES)/derived/happiness-frustration-midpoint.json \
	$(CASES)/derived/pay-day-connected.json \
	$(CASES)/derived/pay-day-protect.json \
	$(CASES)/derived/pay-day-substitute.json \
	$(CASES)/derived/follow-me-singles-try-rejection.json \
	$(CASES)/derived/lightning-rod-electric-single-target.json \
	$(CASES)/derived/lightning-rod-nonelectric-single-target.json \
	$(CASES)/derived/reflect-physical-baseline.json \
	$(CASES)/derived/reflect-physical-half.json \
	$(CASES)/derived/reflect-critical-baseline.json \
	$(CASES)/derived/reflect-critical-bypass.json \
	$(CASES)/derived/reflect-duration-switch.json \
	$(CASES)/derived/light-screen-special-half.json \
	$(CASES)/derived/sandstorm-toxic-residual-ko.json \
	$(CASES)/derived/boost-strength-baseline.json \
	$(CASES)/derived/boost-bulk-up-downstream.json \
	$(CASES)/derived/boost-growl-switch-reset.json \
	$(CASES)/derived/boost-cap-failure.json \
	$(CASES)/derived/secondary-ember-success.json \
	$(CASES)/derived/secondary-ember-failure.json \
	$(CASES)/derived/secondary-steel-wing-success.json \
	$(CASES)/derived/secondary-steel-wing-failure.json \
	$(CASES)/derived/secondary-protect-block.json \
	$(CASES)/derived/secondary-immunity-no-roll.json \
	$(CASES)/derived/recoil-double-edge-baseline.json \
	$(CASES)/derived/recoil-rock-head-prevention.json \
	$(CASES)/derived/recoil-rock-head-struggle.json \
	$(CASES)/derived/quick-claw-activation.json \
	$(CASES)/derived/quick-claw-failure.json \
	$(CASES)/derived/recoil-protect-no-followup.json \
	$(CASES)/derived/recoil-immunity-no-followup.json \
	$(CASES)/derived/drain-giga-drain-exact.json \
	$(CASES)/derived/drain-giga-drain-clamp.json \
	$(CASES)/derived/drain-giga-drain-overkill.json \
	$(CASES)/derived/drain-protect-no-followup.json \
	$(CASES)/derived/recoil-ko-forced-replacement.json \
	$(CASES)/derived/recoil-ko-terminal.json \
	$(CASES)/derived/multihit-bone-rush-two.json \
	$(CASES)/derived/multihit-bone-rush-five.json \
	$(CASES)/derived/multihit-bone-rush-early-ko.json \
	$(CASES)/derived/multihit-no-count-flying.json \
	$(CASES)/derived/multihit-no-count-levitate.json \
	$(CASES)/derived/multihit-no-count-miss.json \
	$(CASES)/derived/multihit-no-count-protect.json \
	$(CASES)/derived/fixed-seismic-toss-level.json \
	$(CASES)/derived/fixed-seismic-toss-burned.json \
	$(CASES)/derived/fixed-seismic-toss-ghost-immunity.json \
	$(CASES)/derived/fixed-night-shade-level.json \
	$(CASES)/derived/fixed-night-shade-normal-immunity.json \
	$(CASES)/derived/reversal-bracket-20.json \
	$(CASES)/derived/reversal-bracket-40.json \
	$(CASES)/derived/reversal-bracket-80.json \
	$(CASES)/derived/reversal-bracket-100.json \
	$(CASES)/derived/reversal-bracket-150.json \
	$(CASES)/derived/reversal-bracket-200.json \
	$(CASES)/derived/target-adjacent-ally-no-target.json \
	$(CASES)/derived/target-any-sole-foe.json \
	$(CASES)/derived/try-boost-clear-body.json \
	$(CASES)/derived/try-boost-white-smoke.json \
	$(CASES)/derived/try-boost-hyper-cutter.json \
	$(CASES)/derived/try-boost-keen-eye-nonaccuracy.json \
	$(CASES)/derived/substitute-create-break.json \
	$(CASES)/derived/substitute-tickle-bypass.json \
	$(CASES)/derived/substitute-toxic-block.json \
	$(CASES)/derived/substitute-recoil-basis.json \
	$(CASES)/derived/substitute-drain-basis.json \
	$(CASES)/derived/substitute-multihit-breakthrough.json \
	$(CASES)/derived/magic-coat-growl-reflection.json \
	$(CASES)/derived/snatch-howl-steal.json \
	$(CASES)/derived/snatch-calm-mind.json \
	$(CASES)/derived/snatch-pressure-howl.json \
	$(CASES)/derived/snatch-ineligible-expiry.json \
	$(CASES)/derived/mirror-move-growl-called.json \
	$(CASES)/derived/mirror-move-no-history.json \
	$(CASES)/derived/boost-rotation-1.json \
	$(CASES)/derived/boost-rotation-2.json \
	$(CASES)/derived/boost-rotation-3.json \
	$(CASES)/derived/boost-rotation-4.json \
	$(CASES)/derived/boost-rotation-5.json \
	$(CASES)/derived/boost-rotation-6.json \
	$(CASES)/derived/boost-rotation-7.json \
	$(CASES)/derived/boost-rotation-8.json \
	$(CASES)/derived/boost-rotation-9.json \
	$(CASES)/derived/boost-flash-keen-eye.json \
	$(CASES)/derived/boost-agility-queue-order.json \
	$(CASES)/derived/boost-positive-filter-clear-white.json \
	$(CASES)/derived/boost-positive-filter-hyper-keen.json \
	$(CASES)/derived/boost-tickle-hyper-cutter.json \
	$(CASES)/derived/boost-accuracy-flash-below.json \
	$(CASES)/derived/boost-accuracy-flash-at.json \
	$(CASES)/derived/boost-accuracy-sand-attack-below.json \
	$(CASES)/derived/boost-accuracy-sand-attack-at.json \
	$(CASES)/derived/boost-accuracy-sweet-scent-below.json \
	$(CASES)/derived/boost-accuracy-sweet-scent-at.json \
	$(CASES)/derived/type-boost-metal-coat-steel-wing.json \
	$(CASES)/derived/type-boost-sharp-beak-wing-attack.json \
	$(CASES)/derived/type-boost-silk-scarf-scratch.json \
	$(CASES)/derived/type-boost-soft-sand-earthquake.json \
	$(CASES)/derived/type-boost-black-glasses-thief.json \
	$(CASES)/derived/type-boost-charcoal-ember.json \
	$(CASES)/derived/type-boost-miracle-seed-giga-drain.json \
	$(CASES)/derived/type-boost-mystic-water-surf.json \
	$(CASES)/derived/type-boost-sea-incense-surf.json \
	$(CASES)/derived/type-boost-mismatch.json \
	$(CASES)/derived/type-boost-water-absorb-cancel.json \
	$(CASES)/derived/type-boost-protect-block.json \
	$(CASES)/derived/type-boost-substitute.json \
	$(CASES)/derived/type-boost-critical.json \
	$(CASES)/derived/type-boost-switch-persistence.json \
	$(CASES)/derived/type-boost-poison-barb-sludge.json \
	$(CASES)/derived/type-boost-spell-tag-shadow-ball.json \
	$(CASES)/derived/type-boost-magnet-thunderbolt.json \
	$(CASES)/derived/type-boost-never-melt-ice-ice-beam.json \
	$(CASES)/derived/type-boost-twisted-spoon-psychic.json \
	$(CASES)/derived/ordinary-attack-cut.json \
	$(CASES)/derived/ordinary-attack-dragonclaw.json \
	$(CASES)/derived/ordinary-attack-drillpeck.json \
	$(CASES)/derived/ordinary-attack-eggbomb.json \
	$(CASES)/derived/ordinary-attack-hornattack.json \
	$(CASES)/derived/ordinary-attack-hydropump.json \
	$(CASES)/derived/ordinary-attack-megahorn.json \
	$(CASES)/derived/ordinary-attack-megakick.json \
	$(CASES)/derived/ordinary-attack-peck.json \
	$(CASES)/derived/ordinary-attack-pound.json \
	$(CASES)/derived/ordinary-attack-rockthrow.json \
	$(CASES)/derived/ordinary-attack-slam.json \
	$(CASES)/derived/ordinary-attack-vinewhip.json \
	$(CASES)/derived/ordinary-attack-visegrip.json \
	$(CASES)/derived/ordinary-attack-waterfall.json \
	$(CASES)/derived/ordinary-attack-watergun.json \
	$(CASES)/derived/status-sleep-clause.json \
	$(CASES)/derived/status-freeze-action.json \
	$(CASES)/derived/status-paralysis-action.json \
	$(CASES)/derived/status-primary-rotation.json \
	$(CASES)/derived/status-primary-rotation-2.json \
	$(CASES)/derived/status-ability-rotation.json \
	$(CASES)/derived/weather-rain-lifecycle.json \
	$(CASES)/derived/weather-sun-replacement.json \
	$(CASES)/derived/weather-sun-freeze-immunity.json \
	$(CASES)/derived/weather-hail-lifecycle.json \
	$(CASES)/derived/weather-rain-water-damage.json \
	$(CASES)/derived/weather-sun-water-damage.json \
	$(CASES)/derived/weather-rain-fire-damage.json \
	$(CASES)/derived/weather-sun-fire-damage.json \
	$(CASES)/derived/weather-cloud-nine-switch.json \
	$(CASES)/derived/weather-cloud-nine-damage-product.json \
	$(CASES)/derived/weather-cloud-nine-residual-product.json \
	$(CASES)/derived/weather-sand-stream-start.json \
	$(CASES)/derived/weather-swift-swim-order.json \
	$(CASES)/derived/weather-swift-swim-paralysis-composition.json \
	$(CASES)/derived/weather-chlorophyll-order.json \
	$(CASES)/derived/weather-swift-swim-tie.json \
	$(CASES)/derived/weather-swift-swim-suppressed.json \
	$(CASES)/derived/weather-rain-dish-order.json \
	$(CASES)/derived/weather-rain-dish-cross-holder-speed.json \
	$(CASES)/derived/weather-rain-dish-clamp-full.json \
	$(CASES)/derived/weather-rain-dish-suppressed.json \
	$(CASES)/derived/weather-rain-dish-switch.json \
	$(CASES)/derived/direct-heal-recover-odd.json \
	$(CASES)/derived/direct-heal-recover-clamp.json \
	$(CASES)/derived/direct-heal-recover-full.json \
	$(CASES)/derived/direct-heal-milk-drink-odd.json \
	$(CASES)/derived/direct-heal-milk-drink-clamp.json \
	$(CASES)/derived/direct-heal-milk-drink-full.json \
	$(CASES)/derived/direct-heal-slack-off-odd.json \
	$(CASES)/derived/direct-heal-slack-off-clamp.json \
	$(CASES)/derived/direct-heal-slack-off-full.json \
	$(CASES)/derived/direct-heal-soft-boiled-odd.json \
	$(CASES)/derived/direct-heal-soft-boiled-clamp.json \
	$(CASES)/derived/direct-heal-soft-boiled-full.json \
	$(CASES)/derived/direct-heal-protect-irrelevant.json \
	$(CASES)/derived/direct-heal-substitute-irrelevant.json \
	$(CASES)/derived/direct-heal-burn-residual.json \
	$(CASES)/derived/direct-heal-switch-persistence.json \
	$(CASES)/derived/direct-heal-snatch-steal.json \
	$(CASES)/derived/confusion-primary-self-hit.json \
	$(CASES)/derived/confusion-supersonic-miss.json \
	$(CASES)/derived/confusion-sweet-kiss-action-success.json \
	$(CASES)/derived/confusion-protect-block.json \
	$(CASES)/derived/confusion-substitute-block.json \
	$(CASES)/derived/confusion-own-tempo.json \
	$(CASES)/derived/confusion-switch-clear.json

SECONDARY_ROTATION_CASES = $(filter-out \
	$(CASES)/derived/secondary-ember-success.json \
	$(CASES)/derived/secondary-ember-failure.json \
	$(CASES)/derived/secondary-steel-wing-success.json \
	$(CASES)/derived/secondary-steel-wing-failure.json \
	$(CASES)/derived/secondary-protect-block.json \
	$(CASES)/derived/secondary-immunity-no-roll.json, \
	$(sort $(wildcard $(CASES)/derived/secondary-*.json)))
CASE_JSON += $(SECONDARY_ROTATION_CASES)
CASE_JSON += $(sort $(wildcard $(CASES)/derived/berry-*.json))
CASE_JSON += $(sort $(wildcard $(CASES)/derived/confusion-secondary-*.json))
CASE_JSON += $(sort $(wildcard $(CASES)/derived/flatter-*.json))
CASE_JSON += $(sort $(wildcard $(CASES)/derived/teeterdance-*.json))
CASE_JSON += $(sort $(wildcard $(CASES)/derived/locked-*.json))
CASE_JSON += $(sort $(wildcard $(CASES)/derived/weather-recovery-*.json))
CASE_JSON += $(sort $(wildcard $(CASES)/derived/weather-ball-*.json))
CASE_JSON += $(sort $(wildcard $(CASES)/derived/forecast-*.json))
CASE_JSON += $(sort $(wildcard $(CASES)/derived/thunder-*.json))
CASE_JSON += $(sort $(wildcard $(CASES)/derived/solar-beam-*.json))
CASE_JSON += \
	$(CASES)/derived/fly-airborne-miss-release.json \
	$(CASES)/derived/fly-thunder-paralysis-abort.json \
	$(CASES)/derived/two-turn-bounce-release.json \
	$(CASES)/derived/two-turn-dig-release.json \
	$(CASES)/derived/two-turn-dive-release.json \
	$(CASES)/derived/two-turn-razorwind-release.json \
	$(CASES)/derived/two-turn-skullbash-release.json \
	$(CASES)/derived/two-turn-skyattack-release.json \
	$(CASES)/derived/fly-release-protect.json \
	$(CASES)/derived/fly-release-switch.json \
	$(CASES)/derived/fly-twister-double.json \
	$(CASES)/derived/bounce-gust-double.json \
	$(CASES)/derived/bounce-sky-uppercut-bypass.json \
	$(CASES)/derived/dig-earthquake-double.json \
	$(CASES)/derived/dive-surf-double.json \
	$(CASES)/derived/dig-sandstorm-immunity.json \
	$(CASES)/derived/dig-hail-immunity.json \
	$(CASES)/derived/dive-sandstorm-immunity.json \
	$(CASES)/derived/dive-hail-immunity.json \
	$(CASES)/derived/fly-sandstorm-not-immune.json \
	$(CASES)/derived/spite-pressure-pp-lifecycle.json \
	$(CASES)/derived/camouflage-normal-switch-reset.json \
	$(CASES)/derived/conversion-current-slot-types.json
CASE_JSON += $(sort $(wildcard $(CASES)/derived/item-*.json))
CASE_JSON += $(sort $(wildcard $(CASES)/derived/multihit-rotation-*.json))
CASE_JSON += $(sort $(wildcard $(CASES)/derived/high-crit-rotation-*.json))
CASE_JSON += $(sort $(wildcard $(CASES)/derived/psywave-*.json))
CASE_JSON += $(sort $(wildcard $(CASES)/derived/recharge-*.json))
CASE_JSON += $(sort $(wildcard $(CASES)/derived/brick-break-*.json))
CASE_JSON += $(sort $(wildcard $(CASES)/derived/leftovers-*.json))
CASE_JSON += $(sort $(wildcard $(CASES)/derived/natural-cure-*.json))
CASE_JSON += $(sort $(wildcard $(CASES)/derived/pressure-*.json))
CASE_JSON += $(sort $(wildcard $(CASES)/derived/damp-*.json))
CASE_JSON += $(sort $(wildcard $(CASES)/derived/flame-body-*.json))
CASE_JSON += $(sort $(wildcard $(CASES)/derived/static-*.json))
CASE_JSON += $(sort $(wildcard $(CASES)/derived/poison-point-*.json))
CASE_JSON += $(sort $(wildcard $(CASES)/derived/effect-spore-*.json))
CASE_JSON += $(sort $(wildcard $(CASES)/derived/rough-skin-*.json))
CASE_JSON += $(sort $(wildcard $(CASES)/derived/shed-skin-*.json))
CASE_JSON += $(sort $(wildcard $(CASES)/derived/guts-closure-*.json))
CASE_JSON += $(sort $(wildcard $(CASES)/derived/speed-boost-*.json))
CASE_JSON += $(sort $(wildcard $(CASES)/derived/volt-absorb-*.json))
CASE_JSON += $(sort $(wildcard $(CASES)/derived/arena-trap-*.json))
CASE_JSON += $(sort $(wildcard $(CASES)/derived/magnet-pull-*.json))
CASE_JSON += $(sort $(wildcard $(CASES)/derived/flinch-*.json))
CASE_JSON += $(sort $(wildcard $(CASES)/derived/scalar-*.json))
CASE_JSON += $(sort $(wildcard $(CASES)/derived/always-hit-*.json))
CASE_JSON += $(sort $(wildcard $(CASES)/derived/partial-trap-*.json))
CASE_JSON += $(sort $(wildcard $(CASES)/derived/passive-item-*.json))
CASE_JSON += $(sort $(wildcard $(CASES)/derived/inert-ability-*.json))
CASE_JSON += $(sort $(wildcard $(CASES)/derived/flail-bracket-*.json))
CASE_JSON += $(sort $(wildcard $(CASES)/derived/admission-*.json))
CASE_JSON += $(sort $(wildcard $(CASES)/derived/paralysis-start-*.json))
CASE_JSON += $(sort $(wildcard $(CASES)/derived/live-hp-power-*.json))
CASE_JSON += $(sort $(wildcard $(CASES)/derived/nightmare-*.json))
CASE_JSON += $(sort $(wildcard $(CASES)/derived/intimidate-*.json))
CASE_JSON += $(sort $(wildcard $(CASES)/derived/trace-*.json))
CASE_JSON += $(sort $(wildcard $(CASES)/derived/color-change-*.json))
CASE_JSON += $(sort $(wildcard $(CASES)/derived/attract-*.json))
CASE_JSON += $(sort $(wildcard $(CASES)/derived/role-play-*.json))
CASE_JSON += $(sort $(wildcard $(CASES)/derived/source-trap-*.json))
CASE_JSON += $(sort $(wildcard $(CASES)/derived/cute-charm-*.json))
CASE_JSON += $(sort $(wildcard $(CASES)/derived/self-destruct-*.json))
CASE_JSON += $(CASES)/derived/faint-order-gen3-explosion-stop.json
CASE_JSON += $(sort $(wildcard $(CASES)/derived/choice-*.json))
CASE_JSON += $(sort $(wildcard $(CASES)/derived/upstream-disable-*.json))
CASE_JSON += $(sort $(wildcard $(CASES)/derived/mist-*.json))
CASE_JSON += $(sort $(wildcard $(CASES)/derived/safeguard-*.json))
CASE_JSON += $(sort $(wildcard $(CASES)/derived/yawn-*.json))
CASE_JSON += $(sort $(wildcard $(CASES)/derived/spikes-*.json))
CASE_JSON += $(sort $(wildcard $(CASES)/derived/screen-*.json))
CASE_JSON += $(sort $(wildcard $(CASES)/derived/drain-family-*.json))
CASE_JSON += $(sort $(wildcard $(CASES)/derived/fixed-literal-*.json))
CASE_JSON += $(sort $(wildcard $(CASES)/derived/target-relative-*.json))
CASE_JSON += $(sort $(wildcard $(CASES)/derived/starter-*.json))
CASE_JSON += $(sort $(wildcard $(CASES)/derived/thick-fat-*.json))
CASE_JSON += $(sort $(wildcard $(CASES)/derived/marvel-scale-*.json))
CASE_JSON += $(sort $(wildcard $(CASES)/derived/stat-item-*.json))
CASE_JSON += $(sort $(wildcard $(CASES)/derived/damage-relay-*.json))
CASE_JSON += $(sort $(wildcard $(CASES)/derived/facade-*.json))
CASE_JSON += $(sort $(wildcard $(CASES)/derived/refresh-*.json))
CASE_JSON += $(sort $(wildcard $(CASES)/derived/psych-up-*.json))
CASE_JSON += $(sort $(wildcard $(CASES)/derived/self-drop-*.json))
CASE_JSON += $(sort $(wildcard $(CASES)/derived/recoil-trio-*.json))
CASE_JSON += $(sort $(wildcard $(CASES)/derived/haze-*.json))
CASE_JSON += $(sort $(wildcard $(CASES)/derived/rest-*.json))
CASE_JSON += $(sort $(wildcard $(CASES)/derived/sleep-clause-*.json))
CASE_JSON += $(sort $(wildcard $(CASES)/derived/synchronize-*.json))
CASE_JSON += $(sort $(wildcard $(CASES)/derived/grouped-*.json))
CASE_JSON += $(CASES)/derived/glare-natural-type-immunity.json
CASE_JSON += $(CASES)/derived/shield-dust-holder-secondary-ownership.json
CASE_JSON += $(sort $(wildcard $(CASES)/derived/sleep-lifecycle-*.json))
CASE_JSON += $(sort $(wildcard $(CASES)/derived/team-cure-*.json))
CASE_JSON += $(sort $(wildcard $(CASES)/derived/freeze-lifecycle-*.json))
CASE_JSON += $(sort $(wildcard $(CASES)/derived/magnitude-*.json))
CASE_JSON += $(sort $(wildcard $(CASES)/derived/sport-*.json))
CASE_JSON += $(filter-out $(CASES)/derived/critical-hit.json, \
	$(sort $(wildcard $(CASES)/derived/critical-*.json)))
CASE_JSON += $(sort $(wildcard $(CASES)/derived/retaliation-*.json))
CASE_JSON += $(sort $(wildcard $(CASES)/derived/hidden-power-*.json))
CASE_JSON += $(CASES)/derived/future-sight-shared-collision-switch-protect-hit.json
CASE_JSON += $(CASES)/derived/future-sight-screen-source-switch.json
CASE_JSON += $(CASES)/derived/future-sight-no-screen-source-switch.json
CASE_JSON += $(CASES)/derived/doom-desire-endure-expiry-miss.json
CASE_JSON += $(CASES)/derived/wish-futuremove-coexist-switch-residual-order.json
CASE_JSON += $(CASES)/derived/upstream-wish-31.json
CASE_JSON += $(CASES)/derived/upstream-wish-64.json
CASE_JSON += $(CASES)/derived/futuremove-fainted-occupant-no-accuracy.json
CASE_JSON += $(CASES)/derived/futuremove-terminal-winner.json
CASE_JSON += $(CASES)/derived/doom-desire-lethal-forced-replacement.json
CASE_JSON += $(CASES)/derived/drag-cancels-queued-move.json
CASE_JSON += $(CASES)/derived/drag-entry-lifecycle-recombination.json
CASE_JSON += $(CASES)/derived/drag-ingrain-block.json
CASE_JSON += $(CASES)/derived/drag-roar-no-eligible.json
CASE_JSON += $(CASES)/derived/drag-roar-one-eligible.json
CASE_JSON += $(CASES)/derived/drag-suction-cups-block.json
CASE_JSON += $(CASES)/derived/drag-whirlwind-multiple-eligible.json
CASE_JSON += $(filter-out $(CASES)/derived/pursuit-oracle-expectations.json, \
	$(sort $(wildcard $(CASES)/derived/pursuit-*.json)))
CASE_JSON += $(CASES)/derived/simultaneous-voluntary-switch-order.json
CASE_JSON += $(sort $(wildcard $(CASES)/derived/charge-gen3-*.json))
CASE_JSON += $(sort $(wildcard $(CASES)/derived/leech-seed-*.json))
CASE_JSON += $(sort $(wildcard $(CASES)/derived/rapid-spin-leech-seed-*.json))
CASE_JSON += $(sort $(wildcard $(CASES)/derived/flash-fire-*.json))
CASE_JSON += $(sort $(wildcard $(CASES)/derived/rage-*.json))
CASE_JSON += $(CASES)/derived/teleport-declarative-rejection.json
CASE_JSON += $(sort $(wildcard $(CASES)/derived/plus-minus-*.json))
CASE_JSON += $(sort $(wildcard $(CASES)/derived/ohko-*.json))
CASE_JSON += $(CASES)/derived/metronome-fissure-flying.json
CASE_JSON += $(CASES)/derived/nature-power-fixed-swift-protect.json
CASE_JSON += $(sort $(wildcard $(CASES)/derived/sleep-talk-*.json))
CASE_JSON += $(sort $(wildcard $(CASES)/derived/curse-*.json))
CASE_JSON += $(sort $(wildcard $(CASES)/derived/truant-*.json))
CASE_JSON += $(sort $(wildcard $(CASES)/derived/pain-split-*.json))
CASE_JSON += $(sort $(wildcard $(CASES)/derived/memento-*.json))
CASE_JSON += $(sort $(wildcard $(CASES)/derived/jump-kick-*.json))
CASE_JSON += $(CASES)/derived/clear-body-negative-cap-order.json
CASE_JSON += $(CASES)/derived/rock-head-does-not-block-crash.json
CASE_JSON += $(CASES)/derived/rock-head-does-not-block-indirect.json
CASE_JSON += $(CASES)/derived/mail-knock-off-removal.json
CASE_JSON += $(CASES)/derived/knock-off-substitute-retains-item.json
CASE_JSON += $(CASES)/derived/thief-held-source-retains-items.json
CASE_JSON += $(CASES)/derived/quick-claw-induced-speed-tie.json
CASE_JSON += $(CASES)/derived/sitrus-knock-off-before-residual.json
CASE_JSON += $(CASES)/derived/immunity-skill-swap-cure.json
CASE_JSON += $(CASES)/derived/thief-target-faint-transfer.json
CASE_JSON += $(CASES)/derived/substitute-routing-product.json
CASE_JSON += $(CASES)/derived/sitrus-status-residual-deferral.json
CASE_JSON += $(CASES)/derived/residual-paralyzed-seeded-leftovers-order.json
CASE_JSON += $(sort $(wildcard $(CASES)/derived/revenge-*.json))
CASE_JSON += $(sort $(wildcard $(CASES)/derived/low-kick-*.json))
CASE_JSON += $(sort $(wildcard $(CASES)/derived/transform-*.json))
CASE_JSON += $(sort $(wildcard $(CASES)/derived/smelling-salts-*.json))
CASE_JSON += $(sort $(wildcard $(CASES)/derived/belly-drum-*.json))
CASE_JSON += $(sort $(wildcard $(CASES)/derived/dream-eater-*.json))
CASE_JSON += $(sort $(wildcard $(CASES)/derived/tri-attack-*.json))
CASE_JSON += $(sort $(wildcard $(CASES)/derived/mimic-*.json))
CASE_JSON += $(sort $(wildcard $(CASES)/derived/sketch-*.json))
CASE_JSON += $(sort $(wildcard $(CASES)/derived/skill-swap-*.json))
CASE_JSON += $(CASES)/derived/insomnia-update-skill-swap.json
CASE_JSON += $(CASES)/derived/vital-spirit-trace-update.json
CASE_JSON += $(CASES)/derived/foresight-immunity-core.json
CASE_JSON += $(CASES)/derived/odor-sleuth-immunity-alias.json
CASE_JSON += $(CASES)/derived/foresight-wonder-guard-independent.json
CASE_JSON += $(CASES)/derived/camouflage-already-normal-dual-type.json
CASE_JSON += $(sort $(wildcard $(CASES)/derived/perish-song-*.json))
CASE_JSON += $(sort $(wildcard $(CASES)/derived/metronome-swagger-*.json))
CASE_JSON += $(sort $(wildcard $(CASES)/derived/bide-*.json))
CASE_JSON += $(sort $(wildcard $(CASES)/derived/fury-cutter-*.json))
CASE_JSON += $(sort $(wildcard $(CASES)/derived/rollout-*.json))
CASE_JSON += $(sort $(wildcard $(CASES)/derived/ice-ball-*.json))
CASE_JSON += $(sort $(wildcard $(CASES)/derived/stockpile-*.json))
CASE_JSON += $(sort $(wildcard $(CASES)/derived/spit-up-*.json))
CASE_JSON += $(sort $(wildcard $(CASES)/derived/swallow-*.json))
CASE_JSON += $(sort $(wildcard $(CASES)/derived/metronome-spit-up-*.json))
CASE_JSON += $(sort $(wildcard $(CASES)/derived/snatch-stockpile-*.json))
CASE_JSON += $(sort $(wildcard $(CASES)/derived/snatch-swallow-*.json))
CASE_JSON += $(sort $(wildcard $(CASES)/derived/baton-pass-*.json))
CASE_JSON += $(sort $(wildcard $(CASES)/derived/conversion2-*.json))
CASE_JSON += $(sort $(wildcard $(CASES)/derived/metronome-minimize-*.json))
CASE_JSON += $(sort $(wildcard $(CASES)/derived/metronome-double-team-*.json))
CASE_JSON += $(sort $(wildcard $(CASES)/derived/focus-punch-*.json))
CASE_JSON += $(sort $(wildcard $(CASES)/derived/destiny-bond-*.json))
CASE_JSON += $(sort $(wildcard $(CASES)/derived/grudge-*.json))
CASE_JSON += $(sort $(wildcard $(CASES)/derived/uproar-*.json))
CASE_JSON += $(sort $(wildcard $(CASES)/derived/imprison-*.json))
CASE_JSON += $(sort $(wildcard $(CASES)/derived/triple-kick-*.json))
CASE_JSON += $(sort $(wildcard $(CASES)/derived/twineedle-*.json))
CASE_JSON += $(sort $(wildcard $(CASES)/derived/secret-power-*.json))
CASE_JSON += $(sort $(wildcard $(CASES)/derived/present-*.json))
CASE_JSON += $(sort $(wildcard $(CASES)/derived/freeze-clause-*.json))
CASE_JSON += $(sort $(wildcard $(CASES)/derived/beat-up-*.json))
CASE_JSON += $(sort $(wildcard $(CASES)/derived/assist-metronome-*.json))
CASE_JSON += $(sort $(wildcard $(CASES)/derived/endless-battle-*.json))
EXPECTED_BOUNDARIES = $(shell node -e 'const fs=require("fs"); console.log(process.argv.slice(1).reduce((n,p)=>n+1+JSON.parse(fs.readFileSync(p,"utf8")).choices.length,0))' $(CASE_JSON))

.PHONY: all test oracle differential clean FORCE

all: native

generated_cases.h: FORCE Makefile $(CASE_JSON) $(CASES)/native-id-map.json \
	$(CASES)/compile-c.js $(CASES)/normalize.js $(CASES)/verify_case.h
	node $(CASES)/compile-c.js $(CASE_JSON) $(CASES)/native-id-map.json > $@.tmp
	mv $@.tmp $@

FORCE:

native: native.c generated_cases.h $(SOURCES) $(HEADERS) $(KERNEL_INCLUDES)
	$(CC) $(CFLAGS) -I$(NATIVE) -I$(CASES) native.c $(SOURCES) -o $@

test: native
	node test-compare.js
	./native gen3-singles2-complete > native.test.complete
	test "$$(wc -l < native.test.complete)" -eq 6
	./native decisions-switch-targets > native.test.switch
	test "$$(wc -l < native.test.switch)" -eq 4
	./native derived-accuracy-miss > native.test.miss
	test "$$(wc -l < native.test.miss)" -eq 2
	./native derived-critical-hit > native.test.crit
	test "$$(wc -l < native.test.crit)" -eq 2
	./native > native.test.all
	test "$$(wc -l < native.test.all)" -eq $(EXPECTED_BOUNDARIES)
	./native > native.test.repeat
	cmp native.test.all native.test.repeat
	./native does-not-exist >/dev/null 2>&1 && exit 1 || true
	rm -f native.test.complete native.test.switch native.test.all native.test.repeat

oracle:
	@test -n "$(POKEMON_SHOWDOWN_DIR)" || \
		(echo "POKEMON_SHOWDOWN_DIR must name the pinned, built, observer-patched checkout" >&2; exit 2)
	@set -e; temporary="oracle.jsonl.tmp.$$$$"; \
	trap 'rm -f "$$temporary"' EXIT HUP INT TERM; : > "$$temporary"; \
	for fixture in $(CASE_JSON); do \
		POKEMON_SHOWDOWN_DIR="$(POKEMON_SHOWDOWN_DIR)" node oracle.js "$$fixture" >> "$$temporary"; \
	done; \
	mv "$$temporary" oracle.jsonl; trap - EXIT HUP INT TERM

differential: native
	@test -n "$(POKEMON_SHOWDOWN_DIR)" || \
		(echo "POKEMON_SHOWDOWN_DIR must name the pinned, built, observer-patched checkout" >&2; exit 2)
	@set -e; run_dir=$$(mktemp -d "$${TMPDIR:-/tmp}/pokemon-gen3-differential.XXXXXX"); \
	trap 'rm -rf "$$run_dir"' EXIT HUP INT TERM; : > "$$run_dir/oracle.jsonl"; \
	for fixture in $(CASE_JSON); do \
		POKEMON_SHOWDOWN_DIR="$(POKEMON_SHOWDOWN_DIR)" node oracle.js "$$fixture" >> "$$run_dir/oracle.jsonl"; \
	done; \
	./native > "$$run_dir/native.jsonl"; \
	node compare.js "$$run_dir/oracle.jsonl" "$$run_dir/native.jsonl"; \
	: > "$$run_dir/oracle.repeat.jsonl"; \
	for fixture in $(CASE_JSON); do \
		POKEMON_SHOWDOWN_DIR="$(POKEMON_SHOWDOWN_DIR)" node oracle.js "$$fixture" >> "$$run_dir/oracle.repeat.jsonl"; \
	done; \
	cmp "$$run_dir/oracle.jsonl" "$$run_dir/oracle.repeat.jsonl"; \
	./native > "$$run_dir/native.repeat.jsonl"; \
	cmp "$$run_dir/native.jsonl" "$$run_dir/native.repeat.jsonl"; \
	cp "$$run_dir/oracle.jsonl" "oracle.jsonl.tmp.$$$$"; \
	cp "$$run_dir/native.jsonl" "native.jsonl.tmp.$$$$"; \
	mv "oracle.jsonl.tmp.$$$$" oracle.jsonl; \
	mv "native.jsonl.tmp.$$$$" native.jsonl; \
	trap - EXIT HUP INT TERM; rm -rf "$$run_dir"

clean:
	rm -f native native_san generated_cases.h generated_cases.h.tmp native.jsonl native.jsonl.tmp.* oracle.jsonl oracle.jsonl.tmp.* oracle.repeat.jsonl native.repeat.jsonl native.test.*
	rm -rf native_san.dSYM
