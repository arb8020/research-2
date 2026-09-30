'use strict';

const assert = require('assert');
const fs = require('fs');
const path = require('path');
const {validateRuntimeRegistrationContract} = require('./runtime-registration-contract');

const checked = JSON.parse(fs.readFileSync(path.join(__dirname, 'runtime-registration-census.json'), 'utf8'));
const copy = value => JSON.parse(JSON.stringify(value));
const trappingVariants = value => value.gen3ou_applicable_dynamic_declarations.filter(record =>
	record.source.file === 'test/sim/misc/trapmoves.js').flatMap(record => record.variants);

validateRuntimeRegistrationContract(checked);

const hiddenBatonGap = copy(checked);
const baton = trappingVariants(hiddenBatonGap).find(variant =>
	variant.assertion === 'permits-baton-pass-switch');
baton.evidence.native_units = [];
baton.evidence.differential_cases = [];
baton.evidence.descriptor_equivalence = null;
baton.required_case = 'regressed-baton-pass-proof';
assert.throws(() => validateRuntimeRegistrationContract(hiddenBatonGap), /Baton Pass/);

const missingInstance = copy(checked);
const trappingDeclaration = missingInstance.gen3ou_applicable_dynamic_declarations.find(record =>
	record.source.file === 'test/sim/misc/trapmoves.js');
trappingDeclaration.variants.pop();
assert.throws(() => validateRuntimeRegistrationContract(missingInstance), /41 distinct/);

const contradictoryProof = copy(checked);
const proven = trappingVariants(contradictoryProof).find(variant =>
	variant.assertion !== 'permits-baton-pass-switch');
proven.required_case = 'contradictory-placeholder';
assert.throws(() => validateRuntimeRegistrationContract(contradictoryProof), /proof and a required case/);

console.log('runtime registration contract mutation tests passed');
