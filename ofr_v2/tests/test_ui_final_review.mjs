import test from 'node:test'
import assert from 'node:assert/strict'
import { InputRevision, hasPlanningForecast, roadDisplay, supportedPeople } from '../app/frontend/src/planValidity.ts'
test('late response is rejected even after inputs change back', async () => {
 const gate = new InputRevision(); const first = gate.update('A')
 let finish; const response = new Promise(resolve => { finish = resolve })
 const accepted = response.then(() => gate.isCurrent(first))
 gate.update('B'); gate.update('A'); finish()
 assert.equal(await accepted, false)
 assert.equal(gate.isCurrent(gate.update('A')), true)
})
test('unchanged inputs retain result validity', () => {
 const gate = new InputRevision(); const first = gate.update('A')
 assert.equal(gate.update('A'),first); assert.equal(gate.isCurrent(first),true)
})
test('zero demand is valid only with an identified input source', () => {
 assert.equal(hasPlanningForecast('manual',[0,0,0,0]),true)
 assert.equal(hasPlanningForecast(null,[0,0,0,0]),false)
 for(const values of [[1,2,3],[1,2,3,NaN],[1,2,3,-1]]) assert.equal(hasPlanningForecast('manual',values),false)
})
test('custom and synthetic graphs never inherit official provenance', () => {
 assert.equal(roadDisplay({road_graph_data_kind:'synthetic'}).official,false)
 assert.equal(roadDisplay({road_graph_data_kind:'operational'}).official,false)
 assert.equal(roadDisplay({}).official,false)
 assert.equal(roadDisplay({road_graph_data_kind:'official_geometry_scenario'}).official,true)
})

test('demand preview rounds people before deriving liters and daily rations', () => {
 const n = supportedPeople(2063,10)
 assert.equal(n,207); assert.equal(n*3*15,9315); assert.equal(n*3,621)
 assert.equal(supportedPeople(2060,10),206)
 assert.equal(supportedPeople(20,5),1)
})
