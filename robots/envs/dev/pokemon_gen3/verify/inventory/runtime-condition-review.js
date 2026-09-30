'use strict';

const {identity} = require('./runtime-condition-source-audit');

const OWNERSHIP = new Set(['lifecycle-owning', 'payload-only', 'debug/test-only']);

function reconcileSourceCensus(live, reviewed) {
	const reviewedByIdentity = new Map(reviewed.map(record => [identity(record), record]));
	const liveIdentities = new Set(live.map(identity));
	const unknown = live.filter(record => !reviewedByIdentity.has(identity(record)));
	const stale = reviewed.filter(record => !liveIdentities.has(identity(record)));
	if (unknown.length || stale.length) {
		throw new Error(`runtime condition review changed: ${unknown.length} unknown, ${stale.length} stale; ` +
			'review each source row before updating the ledger');
	}
	return live.map(record => {
		const prior = reviewedByIdentity.get(identity(record));
		if (!OWNERSHIP.has(prior.ownership) || !prior.gen3ou || !prior.evidence) {
			throw new Error(`unreviewed runtime condition row: ${identity(record)}`);
		}
		return {...record, ownership: prior.ownership, gen3ou: prior.gen3ou,
			evidence: prior.evidence};
	});
}

module.exports = {OWNERSHIP, reconcileSourceCensus};
