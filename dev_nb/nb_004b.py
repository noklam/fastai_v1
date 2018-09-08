
        #################################################
        ### THIS FILE WAS AUTOGENERATED! DO NOT EDIT! ###
        #################################################

from nb_004a import *
from fast_progress import master_bar,progress_bar

@dataclass
class DeviceDataLoader():
    dl: DataLoader
    device: torch.device
    tfms: List[Callable]=None

    def __len__(self): return len(self.dl)

    def proc_batch(self,b):
        b = to_device(self.device,b)
        return b if self.tfms is None else self.tfms(b)

    def __iter__(self):
        self.gen = map(self.proc_batch, self.dl)
        return iter(self.gen)

    @classmethod
    def create(cls, *args, device=default_device, tfms=tfms, **kwargs):
        return cls(DataLoader(*args, **kwargs), device=device, tfms=tfms)

nb_002b.DeviceDataLoader = DeviceDataLoader

def fit(epochs, model, loss_fn, opt, data, callbacks=None, metrics=None, pbar=None):
    cb_handler = CallbackHandler(callbacks)
    cb_handler.on_train_begin()
    if pbar is None: pbar = master_bar(range(epochs))

    for epoch in pbar:
        model.train()
        cb_handler.on_epoch_begin()

        for xb,yb in progress_bar(data.train_dl, parent=pbar):
            xb, yb = cb_handler.on_batch_begin(xb, yb)
            loss,_ = loss_batch(model, xb, yb, loss_fn, opt, cb_handler)
            if cb_handler.on_batch_end(loss): break

        if hasattr(data,'valid_dl') and data.valid_dl is not None:
            model.eval()
            with torch.no_grad():
                *val_metrics,nums = zip(*[loss_batch(model, xb, yb, loss_fn, cb_handler=cb_handler, metrics=metrics)
                                for xb,yb in progress_bar(data.valid_dl, parent=pbar)])
            val_metrics = [np.sum(np.multiply(val,nums)) / np.sum(nums) for val in val_metrics]

        else: val_metrics=None
        if cb_handler.on_epoch_end(val_metrics): break

    cb_handler.on_train_end()

@dataclass
class Learner():
    "Object that wraps together some data, a model, a loss function and an optimizer"

    data:DataBunch
    model:nn.Module
    opt_fn:Callable=AdamW
    loss_fn:Callable=F.cross_entropy
    metrics:Collection[Callable]=None
    true_wd:bool=True
    wd:Floats=1e-6
    path:str = 'models'
    callback_fns:Collection[Callable]=None
    layer_groups:Collection[nn.Module]=None
    def __post_init__(self):
        self.path = Path(self.path)
        self.path.mkdir(parents=True, exist_ok=True)
        self.model = self.model.to(self.data.device)
        if not self.layer_groups: self.layer_groups = [self.model]
        self.callback_fns = listify(self.callback_fns)
        self.callbacks = []

    def fit(self, epochs:int, lr:Floats, wd:Floats=None, callbacks:Collection[Callback]=None):
        if wd is None: wd = self.wd
        self.create_opt(lr, wd)
        if callbacks is None: callbacks = []
        callbacks += [cb(self) for cb in self.callback_fns]
        pbar = master_bar(range(epochs))
        self.recorder = Recorder(self.opt, epochs, self.data.train_dl, pbar)
        callbacks = [self.recorder] + self.callbacks + callbacks
        fit(epochs, self.model, self.loss_fn, self.opt, self.data, callbacks=callbacks, metrics=self.metrics, pbar=pbar)

    def create_opt(self, lr:Floats, wd:Floats=0.):
        lrs = listify(lr, self.layer_groups)
        opt = self.opt_fn([{'params': trainable_params(l), 'lr':lr} for l,lr in zip(self.layer_groups, lrs)])
        self.opt = OptimWrapper(opt, wd=wd, true_wd=self.true_wd)


    def split(self, split_on):
        if isinstance(split_on,Callable): split_on = split_on(self.model)
        self.layer_groups = split_model(self.model, split_on)

    def freeze_to(self, n):
        for g in self.layer_groups[:n]:
            for l in g:
                if not isinstance(l, bn_types):
                    for p in l.parameters(): p.requires_grad = False
        for g in self.layer_groups[n:]:
            for p in g.parameters(): p.requires_grad = True

    def freeze(self):
        assert(len(self.layer_groups)>1)
        self.freeze_to(-1)

    def unfreeze(self): self.freeze_to(0)

    def save(self, name): torch.save(self.model.state_dict(), self.path/f'{name}.pth')
    def load(self, name): self.model.load_state_dict(torch.load(self.path/f'{name}.pth'))

import nb_004a
nb_004a.Learner = Learner

@dataclass
class Recorder(Callback):
    opt: torch.optim
    nb_epoch:int
    train_dl: DeviceDataLoader = None
    pbar: master_bar = None

    def on_train_begin(self, **kwargs):
        self.losses,self.val_losses,self.lrs,self.moms,self.metrics,self.nb_batches = [],[],[],[],[],[]

    def on_batch_begin(self, **kwargs):
        self.lrs.append(self.opt.lr)
        self.moms.append(self.opt.mom)

    def on_backward_begin(self, smooth_loss, **kwargs):
        #We record the loss here before any other callback has a chance to modify it.
        self.losses.append(smooth_loss)
        if self.pbar is not None and hasattr(self.pbar,'child'):
            self.pbar.child.comment = f'{smooth_loss:.4f}'

    def on_epoch_end(self, epoch, num_batch, smooth_loss, last_metrics, **kwargs):
        self.nb_batches.append(num_batch)
        if last_metrics is not None:
            self.val_losses.append(last_metrics[0])
            if len(last_metrics) > 1: self.metrics.append(last_metrics[1:])
            self.pbar.write(f'{epoch}, {smooth_loss}, {last_metrics}')
        else:  self.pbar.write(f'{epoch}, {smooth_loss}')

    def plot_lr(self, show_moms=False):
        iterations = list(range(len(self.lrs)))
        if show_moms:
            _, axs = plt.subplots(1,2, figsize=(12,4))
            axs[0].plot(iterations, self.lrs)
            axs[1].plot(iterations, self.moms)
        else: plt.plot(iterations, self.lrs)

    def plot(self, skip_start=10, skip_end=5):
        lrs = self.lrs[skip_start:-skip_end] if skip_end > 0 else self.lrs[skip_start:]
        losses = self.losses[skip_start:-skip_end] if skip_end > 0 else self.losses[skip_start:]
        _, ax = plt.subplots(1,1)
        ax.plot(lrs, losses)
        ax.set_xscale('log')

    def plot_losses(self):
        _, ax = plt.subplots(1,1)
        iterations = list(range(len(self.losses)))
        ax.plot(iterations, self.losses)
        val_iter = self.nb_batches
        val_iter = np.cumsum(val_iter)
        ax.plot(val_iter, self.val_losses)

    def plot_metrics(self):
        assert len(self.metrics) != 0, "There is no metrics to plot."
        _, axes = plt.subplots(len(self.metrics[0]),1,figsize=(6, 4*len(self.metrics[0])))
        val_iter = self.nb_batches
        val_iter = np.cumsum(val_iter)
        axes = axes.flatten() if len(self.metrics[0]) != 1 else [axes]
        for i, ax in enumerate(axes):
            values = [met[i] for met in self.metrics]
            ax.plot(val_iter, values)

import nb_004
nb_004.Recorder = Recorder

@dataclass
class ShowGraph(Callback):
    learn:Learner

    def on_epoch_end(self, last_metrics, **kwargs):
        if last_metrics is not None:
            rec = learn.recorder
            iters = list(range(len(rec.losses)))
            val_iter = np.array(rec.nb_batches).cumsum()
            x_bounds = (0, (rec.nb_epoch - len(rec.nb_batches)) * rec.nb_batches[-1] + len(rec.losses))
            y_bounds = (0, max((max(rec.losses), max(rec.val_losses))))
            rec.pbar.update_graph([(iters, rec.losses), (val_iter, rec.val_losses)], x_bounds, y_bounds)