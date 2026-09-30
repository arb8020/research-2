#!/usr/bin/env node
'use strict';

const path = require('path');
const {validateCampaignFailure} = require('./artifact');

if (process.argv.length !== 3) {
	throw new Error('usage: node replay-artifact.js ARTIFACT_DIR');
}
const target = path.resolve(process.argv[2]);
const metadata = validateCampaignFailure(target);
console.log(`validated ${metadata.kind} artifact: ${target}`);
console.log(`replay mode: ${metadata.replay.mode}`);
