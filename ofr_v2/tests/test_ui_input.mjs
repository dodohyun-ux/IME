import test from 'node:test'
import assert from 'node:assert/strict'
import { emptyLogistics, buildLogistics, buildRoadPlanning, withSyntheticItemConditions } from '../app/frontend/src/logisticsInput.ts'

const inventory = { water: 100, food: 0, hygiene_kit: 0, blanket: 0 }
test('UI road input keeps common inventory conditions, excludes weekly routes and ties planning to forecast', () => {
  const draft=withSyntheticItemConditions(emptyLogistics())
  const body=buildLogistics(draft,'Medyka',inventory)
  assert.equal(body.initial_lots[0].quantity,100)
  assert.equal(body.vehicles,undefined)
  assert.equal(body.routes,undefined)
  assert.deepEqual(buildRoadPlanning(draft,'2026-01-26'),{warehouse_id:'przemysl-lwowska-36',truck_count:1,reference_date:'2026-01-26'})
})
test('old saved drafts preserve weekly input and disabled mode', () => {
  const draft=withSyntheticItemConditions({enabled:true,fields:{},advanced:null})
  Object.assign(draft.fields,{payload:'12000',volume:'40',transit:'0',roundtrip:'1',tripcost:'250',crossing:'0'})
  for(let w=1;w<=4;w++)Object.assign(draft.fields,{['available_'+w]:'3',['slots_'+w]:'3'})
  assert.equal(buildLogistics(draft,'Medyka',inventory).routes[0].destination,'Medyka')
  assert.equal(buildRoadPlanning(draft,'2026-01-26'),undefined)
  assert.equal(buildLogistics({...draft,enabled:false},'Medyka',inventory),undefined)
})
test('advanced official road JSON accepted, mismatched and mixed destinations rejected', () => {
  const draft={...emptyLogistics(),advanced:{road_network:{destination_site:'Dorohusk'}}}
  assert.equal(buildLogistics(draft,'Dorohusk',inventory),draft.advanced)
  assert.equal(buildRoadPlanning(draft,'2026-01-26'),undefined)
  assert.throws(()=>buildLogistics(draft,'Medyka',inventory))
  assert.throws(()=>buildLogistics({...draft,advanced:{...draft.advanced,routes:[]}},'Dorohusk',inventory))
})
test('fleet bounds and physical weight validation', () => {
  for(const count of ['0','4','1.5',''])assert.throws(()=>buildRoadPlanning({...emptyLogistics(),truckCount:count},'2026-01-26'))
  const draft=withSyntheticItemConditions(emptyLogistics());draft.fields.weight_food='0'
  assert.throws(()=>buildLogistics(draft,'Medyka',inventory))
})

test('transport controls transmit explicit quote and rest assumptions and reject invalid speed', () => {
  const draft={...emptyLogistics(),overnightReturn:false,intermediateRest:true,
    fields:{transport_speed_kph:'30',transport_cost_per_hour:'2',transport_overnight_cost:'50'}}
  assert.deepEqual(buildRoadPlanning(draft,'2026-01-26').transport_controls,
    {speed_kph:30,cost_per_hour:2,overnight_cost:50,allow_overnight_return:false,assumed_intermediate_rest:true})
  for (const v of ['0','29','91','Infinity','abc']) assert.throws(()=>buildRoadPlanning({...draft,fields:{transport_speed_kph:v}},'2026-01-26'))
})
