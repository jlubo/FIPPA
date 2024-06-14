#!/usr/bin/env python3
"""Arbor simulation of a single cell

Arbor simulation of a single cell receiving inhibitory and plastic
excitatory stimulus.
"""

import itertools
import json
import arbor
import numpy

def generate_poisson_spike_train(rate, duration):
    """Returns a Poisson spike train.

    rate -- the rate of the spike train
    duration -- the duration of the spike train
    rng -- random number generator
    """

    n_events = numpy.round(rate * duration)

    if n_events:
        size = numpy.random.poisson(n_events)
        return numpy.sort(numpy.random.uniform(0.0, duration, size))

    return numpy.array([])

class SingleRecipe(arbor.recipe):
    """Implementation of Arbor simulation recipe."""

    def __init__(self, config, cat_file):
        """Initialize the recipe from config."""

        # The base C++ class constructor must be called first, to ensure that
        # all memory in the C++ class is initialized correctly.
        arbor.recipe.__init__(self)

        # load custom catalogue
        catalogue = arbor.load_catalogue(cat_file)

        self.the_props = arbor.neuron_cable_properties()
        self.the_cat = catalogue
        self.the_cat.extend(arbor.default_catalogue(), "")
        self.the_props.catalogue = self.the_cat

        self.config = config

    def num_cells(self):
        """Return the number of cells."""
        return 1

    def num_sources(self, gid):
        """Return the number of spikes sources on gid."""
        assert gid == 0
        return 1

    def num_targets(self, gid):
        """Return the number of post-synaptic targets on gid."""
        assert gid == 0
        return 2

    def cell_kind(self, gid):
        """Return type of cell with gid."""
        assert gid == 0
        return arbor.cell_kind.cable

    def cell_description(self, gid):
        """Return cell description of gid."""
        assert gid == 0

        neuron_config = self.config["neuron"]

        # morphology
        tree = arbor.segment_tree()
        radius = neuron_config["radius"]

        tree.append(arbor.mnpos,
                    arbor.mpoint(-radius, 0, 0, radius),
                    arbor.mpoint(radius, 0, 0, radius),
                    tag=1)

        labels = arbor.label_dict({'center': '(location 0 0.5)'})

        # cell mechanism
        decor = arbor.decor()
        decor.set_property(Vm=neuron_config["e_leak"], cm=0.01)
        lif = arbor.mechanism(neuron_config["type"])
        v_thresh = neuron_config["v_thresh"]
        lif.set("e_thresh", v_thresh)
        lif.set("e_reset", neuron_config["v_reset"])
        lif.set("g_reset", neuron_config["g_reset"])
        lif.set("g_leak", neuron_config["g_leak"])
        lif.set("tau_refrac", neuron_config["t_ref"])
        decor.paint('(all)', arbor.density(lif))
        decor.place('"center"', arbor.threshold_detector(v_thresh), "spike_detector")

        # plastic synapse
        syn_config_homeostasis = self.config["stimulus"]["steady"]
        mech_expsyn_homeostasis = arbor.mechanism('expsyn_homeostasis')
        mech_expsyn_homeostasis.set('tau', syn_config_homeostasis["tau"])
        mech_expsyn_homeostasis.set('e', syn_config_homeostasis["reversal_potential"])
        mech_expsyn_homeostasis.set('dw_plus', syn_config_homeostasis["dw_plus"])
        mech_expsyn_homeostasis.set('dw_minus', syn_config_homeostasis["dw_minus"])
        mech_expsyn_homeostasis.set('w_max', syn_config_homeostasis["w_max"])
        decor.place('"center"', arbor.synapse(mech_expsyn_homeostasis), "expsyn_homeostasis")

        # static synapse
        syn_config = self.config["stimulus"]["varying"]
        mech_expsyn_varying = arbor.mechanism('expsyn')
        mech_expsyn_varying.set('tau', syn_config["tau"])
        mech_expsyn_varying.set('e', syn_config["reversal_potential"])
        decor.place('"center"', arbor.synapse(mech_expsyn_varying), "expsyn")

        return arbor.cable_cell(tree, decor, labels)

    def event_generators(self, gid):
        """Return event generators on gid."""
        assert gid == 0

        syn_config_steady = self.config["stimulus"]["steady"]
        syn_config_varying = self.config["stimulus"]["varying"]

        # generate spikes for steady input
        dt = syn_config_steady["dt"]/1000.
        stimulus_times_steady = numpy.concatenate([generate_poisson_spike_train(rate, dt) + dt*i for i, rate in enumerate(syn_config_steady["rates"])])
        stimulus_times_steady *= 1000.
        #numpy.savetxt("arbor_spikes_steady.dat", stimulus_times_steady)

        # generate spikes for varying input
        dt = syn_config_varying["dt"]/1000.
        stimulus_times_varying = numpy.concatenate([generate_poisson_spike_train(rate, dt) + dt*i for i, rate in enumerate(syn_config_varying["rates"])])
        stimulus_times_varying *= 1000.
        #numpy.savetxt("arbor_spikes_varying.dat", stimulus_times_varying)

        # store varying input rate
        input_dts = numpy.arange(0., len(syn_config_varying["rates"])*dt*1000., dt*1000.)
        input_x = list(itertools.chain(*zip(input_dts, input_dts)))
        input_y = [0] + list(itertools.chain(*zip(syn_config_varying["rates"], syn_config_varying["rates"])))[:-1]
        input_stacked = numpy.column_stack([input_x, input_y])
        numpy.savetxt("arbor_input.dat", input_stacked)

        spike_steady = arbor.event_generator("expsyn_homeostasis", syn_config_steady["weight"], arbor.explicit_schedule(stimulus_times_steady))
        spike_varying = arbor.event_generator("expsyn", syn_config_varying["weight"], arbor.explicit_schedule(stimulus_times_varying))

        return [spike_steady, spike_varying]

    def probes(self, gid):
        """Return probes on gid."""
        assert gid == 0

        return [arbor.cable_probe_membrane_voltage('"center"'),
                arbor.cable_probe_point_state(0, "expsyn_homeostasis", "g"),
                arbor.cable_probe_point_state(1, "expsyn", "g"),
                arbor.cable_probe_point_state(0, "expsyn_homeostasis", "weight_plastic")]

    def global_properties(self, kind):
        """Return the global properties."""
        assert kind == arbor.cell_kind.cable

        return self.the_props


def main(config_file, catalogue):
    """Runs simulation and stores results."""

    # set up simulation and run
    config = json.load(open(config_file, 'r'))
    recipe = SingleRecipe(config, catalogue)

    context = arbor.context()
    domains = arbor.partition_load_balance(recipe, context)
    sim = arbor.simulation(recipe, context, domains)

    sim.record(arbor.spike_recording.all)

    reg_sched = arbor.regular_schedule(config["simulation"]["dt"])
    handle_mem = sim.sample((0, 0), reg_sched)
    handle_ge = sim.sample((0, 1), reg_sched)
    handle_gi = sim.sample((0, 2), reg_sched)
    handle_weight_plastic = sim.sample((0, 3), reg_sched)

    sim.run(tfinal=config["simulation"]["runtime"],
            dt=config["simulation"]["dt"])

    # readout traces and spikes
    data_mem, _ = sim.samples(handle_mem)[0]
    data_ge, _ = sim.samples(handle_ge)[0]
    data_gi, _ = sim.samples(handle_gi)[0]
    data_weight_plastic, _ = sim.samples(handle_weight_plastic)[0]

    # collect data and store
    data_stacked = numpy.column_stack(
        [data_mem[:, 0], data_mem[:, 1], data_ge[:, 1], data_gi[:, 1], data_weight_plastic[:, 1]])

    spike_times = sorted([s[1] for s in sim.spikes()])

    return data_stacked, spike_times


if __name__ == '__main__':

    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('config', help="name of config file")
    parser.add_argument('num_trials', type=int, help="number of trials to consider")
    parser.add_argument('--catalogue', help="name of catalogue file library", default="homeostasis-catalogue.so")
    args = parser.parse_args()

    num_trials = args.num_trials
    data_stacked_sum = numpy.array([])
    spike_times_all = []
    for i in range(num_trials):
        data_stacked, spike_times = main(args.config, args.catalogue)
        if data_stacked_sum.size == 0:
            data_stacked_sum = numpy.array(data_stacked)
        else:
            data_stacked_sum += data_stacked
        spike_times_all.extend(spike_times)
    
    numpy.savetxt(f'arbor_traces.dat', data_stacked_sum / num_trials)
    numpy.savetxt(f'arbor_spikes.dat', spike_times_all)
