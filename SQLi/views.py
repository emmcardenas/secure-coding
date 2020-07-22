import yaml
from datetime import timedelta

from django.db.models import Q
from django.utils import timezone
from django.urls import reverse_lazy
from django.utils.decorators import method_decorator
from django.http import JsonResponse, FileResponse
from django.views.generic import View, FormView, TemplateView
from django.views.decorators.csrf import csrf_exempt
from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import get_object_or_404, redirect

from .models import User, Album, Photo
from .forms import PhotoForm, AlbumForm, SearchForm, AdvancedSearchForm

from ratelimit.decorators import ratelimit
from ratelimit.mixins import RatelimitMixin

import defusedxml.ElementTree as etree


class HomeTemplateView(TemplateView):
    template_name = 'home.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        if self.request.user.is_authenticated:
            home, created = Album.objects.get_or_create(
                name=self.request.user.userprofile.id,
                owner=self.request.user,
            )

            albums = Album.objects.filter(
                owner=self.request.user).exclude(name=home.name)

            photos = Photo.objects.filter(
                owner=self.request.user,
                album=home).order_by('-uploaded_at')

            context['current_album'] = home
            context['albums'] = albums
            context['photos'] = photos

        context['form'] = SearchForm()

        return context


class AlbumTemplateView(LoginRequiredMixin, TemplateView):
    template_name = 'album.html'
    login_url = reverse_lazy('users:login')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        album = get_object_or_404(Album,
                                  name=self.kwargs.get('album'),
                                  owner=self.request.user)

        photos = Photo.objects.filter(
            owner=self.request.user,
            album=album).order_by('-uploaded_at')

        context['current_album'] = album
        context['photos'] = photos
        context['form'] = SearchForm()

        return context


class CreateAlbumFormView(LoginRequiredMixin, FormView):
    form_class = AlbumForm
    template_name = 'create.html'
    login_url = reverse_lazy('users:login')

    def form_valid(self, form):
        album = form.save(commit=False)
        album.owner = self.request.user
        album.save()

        return redirect(reverse_lazy(
            'album:sub-album', kwargs={'album': album.name}))


class SearchPhotosFormView(RatelimitMixin, FormView):
    ratelimit_key = 'get:q'
    ratelimit_rate = '10/s'

    template_name = 'search.html'
    form_class = SearchForm

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        if self.request.user.is_authenticated:
            home, created = Album.objects.get_or_create(
                name=self.request.user.userprofile.id,
                owner=self.request.user,
            )
            context['current_album'] = home

        context['photos'] = []
        context['form'] = self.form_class()

        query = self.request.GET.get('q')
        if query and not query.isspace():
            context['photos'] = Photo.objects.raw(
                'SELECT * FROM albums_photo '
                'WHERE name LIKE "%%%s%%" AND '
                'is_public = 1' % query)
            context['form'].fields['q'].initial = query

        return context


class AdvancedSearchPhotosFormView(RatelimitMixin, FormView):
    ratelimit_key = 'get:q'
    ratelimit_rate = '10/s'

    template_name = 'advanced-search.html'
    form_class = AdvancedSearchForm

    def get_upload_period(self, uploaded_at):
        period = None
        if uploaded_at == 'hours':
            period = timezone.now() - timedelta(hours=24)
        elif uploaded_at == 'week':
            period = timezone.now() - timedelta(days=7)
        elif uploaded_at == 'month':
            period = timezone.now() - timedelta(days=30)
        return period

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        name = self.request.GET.get('name')
        description = self.request.GET.get('description')
        uploaded_at = self.request.GET.get('uploaded_at')

        context['photos'] = []
        context['form'] = self.form_class(
            initial={
                'name': name,
                'description': description,
                'uploaded_at': uploaded_at
            }
        )

        query = Q()
        if name and not name.isspace():
            query &= Q(name__icontains=name)
        if description and not description.isspace():
            query &= Q(description__icontains=description)
        if uploaded_at and not uploaded_at.isspace():
            period = self.get_upload_period(uploaded_at)
            if period:
                query &= Q(uploaded_at__gt=period)

        if query:
            context['photos'] = Photo.objects.filter(query & Q(is_public=True))

        return context


class XMLSearchPhotosAPIView(View):

    @method_decorator(csrf_exempt)
    def dispatch(self, *args, **kwargs):
        return super().dispatch(*args, **kwargs)

    @ratelimit(key='ip', rate='1/s', method=['POST'], block=True)
    def post(self, request, *args, **kwargs):
        parser = etree.DefusedXMLParser(
            # disallow XML with a <!DOCTYPE> processing instruction
            forbid_dtd=True,
            # disallow XML with <!ENTITY> declarations inside the DTD
            forbid_entities=True,
            # disallow any access to remote or local resources in external entities or DTD
            forbid_external=True
        )
        try:
            tree = etree.parse(request, parser=parser)
            query = tree.getroot().find('query').text
        except (etree.ParseError, ValueError) as e:
            return JsonResponse({'error': 'XML parse - %s' % e}, status=400)
        except Exception as e:
            return JsonResponse({'error': str(e)}, status=400)

        photos = []
        if query and not query.isspace():
            photos = [
                {
                    'id': photo.id,
                    'name': photo.name,
                    'description': photo.description,
                    'upload': photo.upload.url,
                    'owner': photo.owner.username,
                } for photo in Photo.objects.filter(
                    name__icontains=query, is_public=True)[:100]
            ]

        return JsonResponse({'photos': photos})


class YAMLSearchPhotosAPIView(View):

    @method_decorator(csrf_exempt)
    def dispatch(self, *args, **kwargs):
        return super().dispatch(*args, **kwargs)

    @ratelimit(key='ip', rate='1/s', method=['POST'], block=True)
    def post(self, request, *args, **kwargs):
        try:
            query = yaml.safe_load(request).get('query')
        except AttributeError as e:
            return JsonResponse({'error': str(e)}, status=400)

        photos = []
        if query and not query.isspace():
            photos = [
                {
                    'id': photo.id,
                    'name': photo.name,
                    'description': photo.description,
                    'upload': photo.upload.url,
                    'owner': photo.owner.username,
                } for photo in Photo.objects.filter(
                    name__icontains=query, is_public=True)[:100]
            ]

        return JsonResponse({'photos': photos})


class UploadPhotoFormView(LoginRequiredMixin, FormView):
    form_class = PhotoForm
    template_name = 'upload.html'
    login_url = reverse_lazy('users:login')

    def get_success_url(self):
        if self.kwargs.get('album') == str(self.request.user.userprofile.id):
            return reverse_lazy('home')
        else:
            return reverse_lazy(
                'album:sub-album',
                kwargs={'album': self.kwargs.get('album')})

    def form_valid(self, form):
        photo = form.save(commit=False)
        photo.album = Album.objects.get(
            name=self.kwargs.get('album'),
            owner=self.request.user,
        )
        if not form.data.get('name'):
            photo.name = photo.upload
        photo.owner = self.request.user
        photo.save()
        return super().form_valid(form)


class PhotoTemplateView(RatelimitMixin, TemplateView):
    ratelimit_key = 'ip'
    ratelimit_rate = '10/s'

    template_name = 'photo.html'

    def set_views(self, photo):
        photo.views += 1
        photo.save()

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        owner = get_object_or_404(User, username=self.kwargs.get('username'))
        photo = get_object_or_404(
            Photo, pk=self.kwargs.get('pk'), owner=owner)
        if self.request.user.pk != owner.pk:
            photo = get_object_or_404(
                Photo, pk=self.kwargs.get('pk'), owner=owner, is_public=True)
            self.set_views(photo)
        context['photo'] = photo
        return context


class PhotoLinkView(RatelimitMixin, LoginRequiredMixin, View):
    ratelimit_key = 'get:pk'
    ratelimit_rate = '10/s'
    login_url = reverse_lazy('users:login')

    def get_object(self):
        return get_object_or_404(
            Photo, pk=self.kwargs.get('pk'), owner=self.request.user)

    def get(self, request, *args, **kwargs):
        photo = self.get_object()
        response = FileResponse(open(photo.upload_thumbnail.path, 'rb'))
        response['content-type'] = 'text/plain'
        return response


class PublicPhotoLinkView(RatelimitMixin, View):
    ratelimit_key = 'get:pk'
    ratelimit_rate = '10/s'

    def get_object(self):
        return get_object_or_404(
            Photo, pk=self.kwargs.get('pk'), is_public=True)

    def get(self, request, *args, **kwargs):
        photo = self.get_object()
        response = FileResponse(open(photo.upload_thumbnail.path, 'rb'))
        response['content-type'] = 'text/plain'
        response['content-security-policy'] = 'sandbox'
        return response


class UserPhotosTemplateView(RatelimitMixin, TemplateView):
    ratelimit_key = 'ip'
    ratelimit_rate = '10/s'

    template_name = 'photos-user.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        owner = get_object_or_404(User, username=self.kwargs.get('username'))
        photos = Photo.objects.filter(owner=owner)
        if self.request.user.pk != owner.pk:
            photos = photos.filter(is_public=True)
        context['photos'] = photos
        context['owner'] = owner
        return context
